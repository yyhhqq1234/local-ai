#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_expand.py -- 七步扩容流水线的「成功判据」闸门（只读，不改任何产物）。

为什么要这个脚本
    七步是 `set -e` 串起来的：命令失败会停，**但命令成功 ≠ 产物正确**。
    本轮已经踩了 20 个静默错，全部是「exit 0 而内容不对」：
      · merge 吃错 adapter 路径 → 目录存在、shard 数对、权重其实没合进去
      · convert 缺 ssm_* 张量（Qwen3.5 混合架构）→ GGUF 能写出来
      · quantize 参数写错 → 输出还是 f16，但命令 rc=0
      · recipe 选错 → .ninfer 能 inspect 通过，对象数不对
      · subsets 与 DATA 不同源 → 全部落 rest，只有一行 warn
      · tar glob 写错 → 包能解，少几个 .pt
    所以每一步都要落到**可数的产物特征**上：文件数 / 字节 / 张量数 / 张量类型 / 条目数。

用法（以下是**唯一**写法的说明，脚本自身绝不写盘）
    python verify_expand.py --step all --root /root/autodl-tmp/kitty-rev
    python verify_expand.py --step 3 --quant out/gguf/xxx.IQ2_S.gguf
    python verify_expand.py --step 5 --inspect-json out/inspect.json
    python verify_expand.py --selftest          # 本机自检（造小样本，验证闸门会红）

退出码：0 全 PASS / 1 有 FAIL / 2 用法错。
每步判据都打印 `[PASS]/[FAIL]/[SKIP]` + 实测值 + 期望值 + 一句「失败说明什么」（静默风险）。
"""
import argparse
import glob
import hashlib
import io
import json
import os
import struct
import sys
import tarfile
import time
import tempfile

# GBK 控制台自保：本文件的输出里有 ≥ / ✓ 之类的非 GBK 字符。在没设
# PYTHONIOENCODING 的 Windows 控制台直接 `python xxx.py --selftest` 会抛
# UnicodeEncodeError —— 看上去像"自检崩了"，其实是编码（#14 的同族复发）。
# 这里把 stdout/stderr 钉成 utf-8，调用者不需要记得设环境变量。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # 非 TextIOWrapper（被重定向/被包裹）时跳过
    pass

# ---- 期望值（云端实测基线；不从这里改就别改，改要同步 AUDIT-HANDOFF §5） ----
EXPECT = {
    "base_shards": 18,          # 27B bf16 分片数
    "base_tensors": 1199,       # 与 27B base 转换时一致（② 用它对齐）
    "gguf_bytes": 51_500_000_000,   # 51.5 G ± 5%
    "quant_bytes": 10_000_000_000,  # 10 G ± 20%
    "ninfer_objects": 787,
    "ninfer_tensors": 783,
    "i2s_types": {14, 15, 19, 20, 21},   # IQ2_XXS/ IQ2_XS / IQ3_S / IQ2_S / IQ4_XS
    "float_types": {0, 1, 28},           # F32 / F16 / BF16（量化后不该大面积出现）
    # act-cache：make_subsets 产出 5 组 ×（train/val）+ rest = 11 个目录，合计 4388
    # （原先只写了 6 个 → 漏 route-val / discipline-* / gen-*；目录名错一个，
    #   本地 train_partial_lora --data-mix 会在几小时后才 FATAL，所以这里必须硬判）
    "act_counts": {"re-train": 287, "re-val": 72,
                   "route-train": 234, "route-val": 58,
                   "discipline-train": 306, "discipline-val": 77,
                   "gen-train": 80, "gen-val": 20,
                   "forge-train": 384, "forge-val": 96,
                   "rest": 2774},
    "act_dirs": 11,
    "act_total": 4388,
    "pack_pt": 3908,
    "pack_layers": 16,
    "pack_dirs": 9,
    # imatrix（gate 2b）：v3 实测 ~27 MB / 524 chunks。字节只做下限（不同 calib 大小差很多）
    "imatrix_min_bytes": 1_000_000,
}

TOL = 0.05          # 字节容差（±5%）
ID2NAME = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 4: "Q5_0", 5: "Q5_1", 6: "Q8_0",
           7: "Q8_1", 8: "Q2_K", 9: "Q3_K", 10: "Q4_K", 11: "Q5_K", 12: "Q6_K",
           13: "Q8_K", 14: "IQ2_XXS", 15: "IQ2_XS", 16: "IQ3_XXS", 17: "IQ1_S",
           18: "IQ4_NL", 19: "IQ3_S", 20: "IQ2_S", 21: "IQ4_XS", 22: "I8", 23: "I16",
           24: "I32", 25: "I64", 26: "F64", 27: "IQ1_M", 28: "BF16"}

def sha16_file(path, cap=None):
    """sha256 前 16 位（cap 给定时只读前 N 字节）。imatrix 指纹用。"""
    h = hashlib.sha256()
    left = cap
    with open(path, "rb") as f:
        while True:
            n = 1 << 20 if left is None else min(1 << 20, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()[:16]


rows = []       # [(step, name, status, detail)]

# --------------------------------------------------------------------------- #
# 假设值 vs 硬判据（v4 雷区 d）
#
# `base_tensors=1199` 是 **v3 的 base 分片总数**（866 text + 333 vision）。
# v4 换 Huihui 基座 + merge 纯 text 之后，text-only GGUF 只有 ~866 个张量 ——
# 拿 1199 去判会 FAIL，而产物其实是对的（人就会去改闸门，闸门从此形同虚设）。
# 反过来更危险：图省事把期望改成 866，则 vision 张量混进 GGUF 也不会被抓。
#
# 处置：这条默认降级为 **WARN**（打印实测值与两个候选期望）；
# 只有**显式**给出（--expect-file / --set base_tensors=866，即实测回来后写进基线）
# 才升级为硬判据。其它键全部照旧硬判。
# --------------------------------------------------------------------------- #
SOFT_KEYS = {"base_tensors"}
EXPLICIT = set()        # 由 --expect-file / --set 明确给出 → 视为已实测，升硬
# 每个期望值的**出处**：内置默认 / 文件 X / --set。WARN 时必须打出来 ——
# 否则以后没人分得清 1199 是「v3 实测」还是「当年拍的」。
EXPECT_SRC = {k: "内置默认（v3 基线/假设值）" for k in EXPECT}


def expect_provenance(key=None):
    """返回 {键: 出处} 或单个键的出处；报告与 WARN 行共用。"""
    if key is None:
        return dict(EXPECT_SRC)
    return EXPECT_SRC.get(key, "?")


def apply_expect_overrides(mapping, source="<override>"):
    """把外部期望值合进 EXPECT 并标记为硬判据。返回实际改动的键列表。"""
    changed = []
    for k, v in (mapping or {}).items():
        if k not in EXPECT:
            print(f"[warn] {source}: 未知期望键 {k!r}（已知：{sorted(EXPECT)}）")
            continue
        if EXPECT[k] != v:
            changed.append(f"{k}: {EXPECT[k]!r} → {v!r}")
        EXPECT[k] = v
        EXPLICIT.add(k)
        EXPECT_SRC[k] = source
    if changed:
        print(f"[expect] {source} 覆盖 {len(changed)} 项（升为硬判据）：" + "；".join(changed))
    else:
        print(f"[expect] {source} 生效（值与默认一致，标记为硬判据）")
    return changed


def rec(step, name, ok, detail, key=None, soft=False):
    """记一条判据。ok=False 且 key∈SOFT_KEYS 且未被显式覆盖 → WARN（不拉红整步），
    因为红的是**假设的期望值**，不是产物。"""
    if key in SOFT_KEYS and key not in EXPLICIT:
        soft = True
    status = "PASS" if ok else ("WARN" if soft else "FAIL")
    if status == "WARN":
        detail = (f"{detail}  ← 假设值，非硬判据"
                  f"（当前期望值 {EXPECT.get(key)!r} 来自「{EXPECT_SRC.get(key, '?')}」；"
                  f"--set {key}=<实测值> 或 --expect-file 可升为硬判）")
    rows.append((step, name, status, detail))
    print(f"[{status}] {step} {name}  {detail}")
    return status in ("PASS", "WARN")


def skip(step, name, detail):
    rows.append((step, name, "SKIP", detail))
    print(f"[SKIP] {step} {name}  {detail}")
    return True


# --------------------------------------------------------------------------- #
# 只读小工具：safetensors 头 / GGUF 头 / 目录计数
# --------------------------------------------------------------------------- #
def st_header(path):
    """读 safetensors 头（前 8 字节是小端 JSON 长度）。不加载张量数据。"""
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n <= 0 or n > 100 * 1024 * 1024:
            raise ValueError(f"头长度异常 {n}")
        return json.loads(f.read(n).decode("utf-8")), 8 + n


def st_first_bytes(path, tensor, nbytes=32):
    """取某张量数据起始 nbytes 字节（用于证明「权重真的被改过」）。"""
    meta, base = st_header(path)
    if tensor not in meta:
        return None
    a, b = meta[tensor]["data_offsets"]
    with open(path, "rb") as f:
        f.seek(base + a)
        return f.read(min(nbytes, b - a))


def _rd(f, fmt):
    return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]


def _rd_str(f):
    n = _rd(f, "<Q")
    return f.read(n).decode("utf-8", "replace")


_VT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<B",
       10: "<Q", 11: "<q", 12: "<d"}


def gguf_scan(path, max_tensors=None):
    """最小 GGUF 解析：返回 {version, tensor_count, kv_count, tensors:[(name,type,dims)]}。

    自己解析而不是依赖 gguf 包：云端 venv 里不一定有，而且这一步要能「只读一个头」。
    """
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"GGUF":
            raise ValueError(f"不是 GGUF（magic={magic!r}）")
        version = _rd(f, "<I")
        n_tensor = _rd(f, "<Q")
        n_kv = _rd(f, "<Q")
        for _ in range(n_kv):                      # 跳过元数据
            _rd_str(f)
            vt = _rd(f, "<I")
            if vt == 8:                            # string
                _rd_str(f)
            elif vt == 9:                          # array
                et = _rd(f, "<I")
                cnt = _rd(f, "<Q")
                if et == 8:
                    for _ in range(cnt):
                        _rd_str(f)
                elif et in _VT:
                    f.seek(struct.calcsize(_VT[et]) * cnt, os.SEEK_CUR)
                else:
                    raise ValueError(f"未知数组元素类型 {et}")
            elif vt in _VT:
                f.seek(struct.calcsize(_VT[vt]), os.SEEK_CUR)
            else:
                raise ValueError(f"未知元数据类型 {vt}")
        tensors = []
        for i in range(n_tensor):
            name = _rd_str(f)
            nd = _rd(f, "<I")
            dims = [_rd(f, "<Q") for _ in range(nd)]
            ttype = _rd(f, "<I")
            f.seek(8, os.SEEK_CUR)                 # offset
            tensors.append((name, ttype, dims))
            if max_tensors and i + 1 >= max_tensors:
                break
    return {"version": version, "tensor_count": n_tensor, "kv_count": n_kv,
            "tensors": tensors}


def du(path):
    """目录/文件字节数（只读 stat，不读内容）。"""
    if os.path.isfile(path):
        return os.path.getsize(path)
    tot = 0
    for r, _d, fs in os.walk(path):
        for fn in fs:
            try:
                tot += os.path.getsize(os.path.join(r, fn))
            except OSError:
                pass
    return tot


def gb(n):
    return f"{n / 2 ** 30:.2f} GiB"


# --------------------------------------------------------------------------- #
# ① merge
# --------------------------------------------------------------------------- #
def check_merge(a):
    st = "①"
    d = a.merged
    if not os.path.isdir(d):
        return rec(st, "merged 目录", False, f"不存在: {d}（merge 没跑完 / 路径错）")
    cfg = os.path.join(d, "config.json")
    if not rec(st, "config.json", os.path.isfile(cfg), cfg):
        return False
    shards = sorted(glob.glob(os.path.join(d, "*.safetensors")))
    shards = [s for s in shards if not s.endswith("index.json")]
    ok = rec(st, "shard 数", len(shards) == EXPECT["base_shards"],
             f"{len(shards)} 个（期望 {EXPECT['base_shards']}）")
    # 张量名集合必须与 base 完全一致：merge 只改值，不改结构
    base_shards = sorted(glob.glob(os.path.join(a.base, "*.safetensors")))
    if not base_shards:
        skip(st, "张量名对齐", f"没找到 base shards（{a.base}）→ 无法比对结构")
    else:
        def names(paths):
            out = set()
            for p in paths:
                out |= {k for k in st_header(p)[0] if not k.startswith("__")}
            return out
        n_m, n_b = names(shards), names(base_shards)
        ok &= rec(st, "张量名集合", n_m == n_b,
                  f"merged {len(n_m)} / base {len(n_b)}"
                  f"{'' if n_m == n_b else '  缺:' + str(sorted(n_b - n_m)[:3])}"
                  f"{'' if n_m == n_b else '  多:' + str(sorted(n_m - n_b)[:3])}")
        if a.spot:
            # 真·判据：LoRA 合并必须改过权重。取第一个存在的 target 模块首 32 字节比对。
            cand = None
            for t in sorted(n_m):
                if any(k in t for k in ("q_proj", "v_proj", "o_proj", "up_proj")):
                    cand = t
                    break
            if cand is None:
                skip(st, "adapter 是否真的合进去", "找不到 LoRA target 张量名（结构变了？）")
            else:
                host_m = next((p for p in shards if cand in st_header(p)[0]), None)
                host_b = next((p for p in base_shards if cand in st_header(p)[0]), None)
                bm = st_first_bytes(host_m, cand) if host_m else None
                bb = st_first_bytes(host_b, cand) if host_b else None
                ok &= rec(st, "adapter 是否真的合进去",
                          bool(bm) and bool(bb) and bm != bb,
                          f"{cand} 首 32B {'不同（已合并）' if bm != bb else '**与 base 完全相同（adapter 没合进去）**'}")
    return ok


# --------------------------------------------------------------------------- #
# ② GGUF（bf16）
# --------------------------------------------------------------------------- #
def check_gguf(a):
    st = "②"
    p = a.gguf
    if not os.path.isfile(p):
        return rec(st, "GGUF 文件", False, f"不存在: {p}")
    n = os.path.getsize(p)
    lo, hi = EXPECT["gguf_bytes"] * (1 - TOL), EXPECT["gguf_bytes"] * (1 + TOL)
    ok = rec(st, "字节数", lo <= n <= hi, f"{gb(n)}（期望 ≈{gb(EXPECT['gguf_bytes'])} ±5%）")
    g = gguf_scan(p)
    ok &= rec(st, "tensor 数", g["tensor_count"] == EXPECT["base_tensors"],
              f"{g['tensor_count']}（期望 {EXPECT['base_tensors']}；v3=1199 含 333 vision，"
              f"v4 text-only ≈866）", key="base_tensors")
    # ssm_* 是 Qwen3.5 混合架构的新张量：缺了 GGUF 照样能写出来
    names = [t[0] for t in g["tensors"]]
    ssm = [x for x in names if "ssm" in x.lower()]
    if ssm:
        rec(st, "ssm_* 张量在场", True, f"{len(ssm)} 个（例：{ssm[0]}）")
    else:
        skip(st, "ssm_* 张量在场", "GGUF 里没有 ssm_*（若该架构本就没有，这条判据不适用）")
    types = {}
    for _n, ty, _d in g["tensors"]:
        types[ty] = types.get(ty, 0) + 1
    top = sorted(types.items(), key=lambda kv: -kv[1])[:3]
    rec(st, "类型分布", True, " ".join(f"{ID2NAME.get(k, k)}×{v}" for k, v in top))
    return ok


# --------------------------------------------------------------------------- #
# ③ quantize
# --------------------------------------------------------------------------- #
def check_imatrix(a):
    """gate 2b：imatrix 存在、够大、而且**比 bf16 GGUF 新**。

    为什么必须比 GGUF 新：imatrix 是「这份权重的量化误差权重表」。换了模型/重新 merge
    之后拿旧 imatrix 去量化，命令照样 rc=0、体积也对，但量化误差在静默变大
    （与「旧 act-cache 配新 base」同一族：文件在 ≠ 口径对）。
    """
    st = "②b"
    imp = a.imatrix
    if not os.path.isfile(imp):
        return rec(st, "imatrix 存在", False,
                   f"缺 {imp}（IQ2_S 必需；生成：llama-imatrix -m <bf16.gguf> -f <calib.txt> -o {imp}）")
    n = os.path.getsize(imp)
    ok = rec(st, "字节数", n > EXPECT["imatrix_min_bytes"],
             f"{n / 2 ** 20:.1f} MiB（下限 {EXPECT['imatrix_min_bytes'] / 2 ** 20:.0f} MiB）")
    # 与 bf16 GGUF 的先后关系
    if os.path.isfile(a.gguf):
        t_i, t_g = os.path.getmtime(imp), os.path.getmtime(a.gguf)
        ok &= rec(st, "imatrix 不早于 bf16.gguf", t_i + 1 >= t_g,
                  f"imatrix {time.strftime('%m-%d %H:%M:%S', time.localtime(t_i))}"
                  f" vs gguf {time.strftime('%m-%d %H:%M:%S', time.localtime(t_g))}"
                  f"（旧 imatrix 配新模型 = 量化误差静默变大）")
    else:
        skip(st, "imatrix 不早于 bf16.gguf", f"没给 bf16 GGUF（{a.gguf}）→ 无法判先后")
    # 出处侧车：calib 来源必须写明，不许"随便一段文本"
    meta_p = imp + ".meta.json"
    if os.path.isfile(meta_p):
        try:
            with open(meta_p, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:                                  # noqa: BLE001
            return rec(st, "imatrix.meta.json 可读", False, f"{meta_p}: {e}")
        need = ("calib", "calib_sha16", "chunks", "llama_commit")
        miss = [k for k in need if not meta.get(k)]
        ok &= rec(st, "imatrix 出处完整", not miss,
                  f"calib={meta.get('calib')} chunks={meta.get('chunks')} "
                  f"commit={meta.get('llama_commit')}" if not miss else f"缺 {miss}")
    else:
        print(f"[WARN] {st} 缺 {os.path.basename(meta_p)}：无法证明 calib 来源"
              f"（calib 质量直接决定 IQ2_S 误差；建议 imatrix 生成步同时写这个侧车）")
        rows.append((st, "imatrix 出处侧车", "WARN", f"缺 {meta_p}"))
    print(f"[info] {st} imatrix={imp} bytes={n} sha16={sha16_file(imp)}")
    return ok


def check_quant(a):
    st = "③"
    p = a.quant
    if not os.path.isfile(p):
        return rec(st, "量化文件", False, f"不存在: {p}")
    n = os.path.getsize(p)
    lo, hi = EXPECT["quant_bytes"] * 0.8, EXPECT["quant_bytes"] * 1.2
    ok = rec(st, "字节数", lo <= n <= hi,
             f"{gb(n)}（期望 ≈{gb(EXPECT['quant_bytes'])} ±20%；若是 51G 说明**没真量化**）")
    g = gguf_scan(p)
    types = {}
    for _n, ty, _d in g["tensors"]:
        types[ty] = types.get(ty, 0) + 1
    n_f = sum(v for k, v in types.items() if k in EXPECT["float_types"])
    n_q = sum(v for k, v in types.items() if k in EXPECT["i2s_types"])
    dist = " ".join(f"{ID2NAME.get(k, k)}×{v}"
                    for k, v in sorted(types.items(), key=lambda kv: -kv[1])[:4])
    ok &= rec(st, "IQ2_S 系列占多数", n_q > (g["tensor_count"] // 2),
              f"量化型 {n_q}/{g['tensor_count']}  浮点型 {n_f}  分布 {dist}")
    ok &= rec(st, "没有退化成 f16/bf16", n_f * 4 < g["tensor_count"],
              f"浮点 {n_f} 个（应只有少量 norm/小张量）")
    ok &= rec(st, "tensor 数与 bf16 一致", g["tensor_count"] == EXPECT["base_tensors"],
              f"{g['tensor_count']} vs {EXPECT['base_tensors']}", key="base_tensors")
    return ok


# --------------------------------------------------------------------------- #
# ⑤ tools.convert → .ninfer
# --------------------------------------------------------------------------- #
def check_ninfer(a):
    st = "⑤"
    if not a.inspect_json:
        return skip(st, "inspect 输出", "没给 --inspect-json（把 tools.artifact.inspect 的输出存成 json 再跑）")
    if not os.path.isfile(a.inspect_json):
        return rec(st, "inspect 输出", False, f"不存在: {a.inspect_json}")
    blob = json.load(open(a.inspect_json, encoding="utf-8"))
    # 兼容几种封装：{"objects":787,...} / {"artifact":{...}} / {"stats":{...}}
    d = blob
    for k in ("artifact", "stats", "summary", "result"):
        if isinstance(d.get(k), dict):
            d = d[k]
            break
    objs = d.get("objects") or d.get("n_objects")
    tens = d.get("tensors") or d.get("n_tensors")
    ok = rec(st, "objects", objs == EXPECT["ninfer_objects"],
             f"{objs}（期望 {EXPECT['ninfer_objects']}）")
    ok &= rec(st, "tensors", tens == EXPECT["ninfer_tensors"],
              f"{tens}（期望 {EXPECT['ninfer_tensors']}）")
    if a.ninfer and os.path.isfile(a.ninfer):
        n = os.path.getsize(a.ninfer)
        rec(st, ".ninfer 字节", n > 0, f"{gb(n)}")
    return ok


# --------------------------------------------------------------------------- #
# ⑥ act-cache
# --------------------------------------------------------------------------- #
def check_actcache(a):
    st = "⑥"
    d = a.actcache
    if not os.path.isdir(d):
        return rec(st, "act-cache 目录", False, f"不存在: {d}")
    subs = sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x)))
    got = {s: len(glob.glob(os.path.join(d, s, "*.pt"))) for s in subs}
    total = sum(got.values())
    print(f"        实测: " + " ".join(f"{k}={v}" for k, v in sorted(got.items()))
          + f"  合计 {total}")

    # ① 目录名集合必须 ⊇ 11 个已知家族；多出来的只 warn（可能是新分组，不能误杀）
    want_dirs = set(EXPECT["act_counts"])
    miss = sorted(want_dirs - set(got))
    extra = sorted(set(got) - want_dirs)
    ok = rec(st, "目录名集合 ⊇ 11 家族", not miss,
             f"{len(got)} 个；缺 {miss}" if miss else f"{len(got)} 个，11 家族齐全")
    if extra:
        print(f"[warn] {st} 多出未登记目录：{extra}（不 FAIL，但 --data-mix 里没有它们）")

    # ② 逐目录条数必须精确相等（不相等就是源错/过滤错，几小时后本地训练才会 FATAL）
    for k in sorted(want_dirs):
        if k in got:
            ok &= rec(st, f"{k} 条数", got[k] == EXPECT["act_counts"][k],
                      f"{got[k]}（期望 {EXPECT['act_counts'][k]}）")

    # ③ 总数必须 4388（= large-mix-plus 行数）
    ok &= rec(st, "总 .pt 数", total == EXPECT["act_total"],
              f"{total}（期望 {EXPECT['act_total']}）")

    # ④ 静默风险：subsets 与 DATA 不同源 → 全部落 rest，只有一行 warn
    rest = got.get("rest", 0)
    named = total - rest
    if rest and (named == 0 or rest > named * 3):
        rec(st, "rest 是否吃掉一切", False,
            f"rest={rest} / 其余={named} —— 分类全落兜底：大概率 subsets 与 DATA 不同源"
            f"（或子集文件路径写错，闸门本该拦但只打了一行 warn）")
    else:
        rec(st, "rest 是否吃掉一切", True, f"rest={rest} / 其余={named}")
    return ok


# --------------------------------------------------------------------------- #
# ⑦ pack
# --------------------------------------------------------------------------- #
def check_pack(a):
    st = "⑦"
    p = a.pack
    if not os.path.isfile(p):
        return rec(st, "tar 文件", False, f"不存在: {p}")
    n_bytes = os.path.getsize(p)
    names, n_dir, n_pt, n_layer = [], 0, 0, 0
    with tarfile.open(p, "r:*") as tf:
        for m in tf:
            names.append(m.name)
            if m.isdir():
                n_dir += 1
            elif m.name.endswith(".pt"):
                n_pt += 1
            elif os.path.basename(m.name).startswith("layer_") and \
                    os.path.basename(m.name).endswith(".safetensors"):
                n_layer += 1
    ok = rec(st, "条目数", len(names) > 0, f"{len(names)} 条  {gb(n_bytes)}")
    ok &= rec(st, ".pt 数", n_pt == EXPECT["pack_pt"], f"{n_pt}（期望 {EXPECT['pack_pt']}）")
    ok &= rec(st, "层文件", n_layer == EXPECT["pack_layers"],
              f"{n_layer}（期望 {EXPECT['pack_layers']}）")
    ok &= rec(st, "目录条目", n_dir >= EXPECT["pack_dirs"],
              f"{n_dir}（期望 ≥{EXPECT['pack_dirs']}）")
    head = [n for n in names if os.path.basename(n).lower().startswith("head")]
    idx = [n for n in names if "index" in os.path.basename(n).lower()]
    ok &= rec(st, "head + index", bool(head) and bool(idx),
              f"head={head[:1]} index={idx[:1]}")

    # ---- act-cache 目录名契约 -------------------------------------------- #
    # 本地 deploy/local_train.ps1 硬编码找 `act-cache`；v4 的目录叫 `act-cache-v4`。
    # 二者一旦对不上，本地一键训练就死在"缺 act-cache"——而 tar 里"看起来有 .pt"。
    # 契约：tar 里有 `act-cache/...`，或者有 `.act-cache-dir-name`（内容是实际目录名）
    # 且该目录也在 tar 里。两者都没有 → FAIL；契约与实际不一致 → WARN。
    top_dirs = {n.split("/", 1)[0] for n in names if "/" in n}
    contract = [n for n in names if os.path.basename(n) == ".act-cache-dir-name"]
    declared = None
    if contract:
        try:
            with tarfile.open(p, "r:*") as tf:
                declared = tf.extractfile(contract[0]).read().decode("utf-8", "replace").strip()
        except Exception as e:                                   # noqa: BLE001
            print(f"[WARN] {st} 读 .act-cache-dir-name 失败：{e}")
    has_default = "act-cache" in top_dirs
    if has_default:
        ok &= rec(st, "act-cache 目录在场", True,
                  f"act-cache/（{sum(1 for n in names if n.startswith('act-cache/') and n.endswith('.pt'))} 个 .pt）")
        if declared and declared != "act-cache":
            print(f"[WARN] {st} 契约文件写的是 {declared!r}，但 tar 里也有 act-cache/ —— 本地会读到两套")
    elif declared and declared in top_dirs:
        ok &= rec(st, "act-cache 目录在场（按契约名）", True,
                  f"{declared}/（{sum(1 for n in names if n.startswith(declared + '/') and n.endswith('.pt'))} 个 .pt）")
    else:
        ok &= rec(st, "act-cache 目录在场", False,
                  f"tar 里既没有 act-cache/，也没有可用的 .act-cache-dir-name"
                  f"（声明={declared!r}；顶层目录={sorted(top_dirs)[:8]}）"
                  f" → 本地 local_train.ps1 会死在『缺 act-cache』")
    return ok


# --------------------------------------------------------------------------- #
# 自检：造样本 → 期望每条闸门都能红
# --------------------------------------------------------------------------- #
def selftest():
    print("=== selftest：每条闸门都要能红（造小样本，不碰真产物）===")
    ok = True
    tmp = tempfile.mkdtemp(prefix="vx-selftest-")

    def st_write(path, tensors, pad=b"\x00" * 8):
        meta = {k: {"dtype": "BF16", "shape": [2], "data_offsets": [i * 4, i * 4 + 4]}
                for i, k in enumerate(tensors)}
        meta["__metadata__"] = {"format": "pt"}
        h = json.dumps(meta).encode()
        with open(path, "wb") as f:
            f.write(struct.pack("<Q", len(h)))
            f.write(h)
            f.write(pad * len(tensors))

    base = os.path.join(tmp, "base")
    merged = os.path.join(tmp, "merged")
    os.makedirs(base)
    os.makedirs(merged)
    st_write(os.path.join(base, "model-00001.safetensors"), ["a.q_proj.weight", "b"])
    # merged：张量名一致但 q_proj 数据不同 → 应 PASS（= 真的合进去了）
    meta = {"a.q_proj.weight": {"dtype": "BF16", "shape": [2], "data_offsets": [0, 4]},
            "b": {"dtype": "BF16", "shape": [2], "data_offsets": [4, 8]}}
    h = json.dumps(meta).encode()
    with open(os.path.join(merged, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "qwen3"}, f)      # ① 的第一条判据就是它
    with open(os.path.join(merged, "model-00001.safetensors"), "wb") as f:
        f.write(struct.pack("<Q", len(h)))
        f.write(h)
        f.write(b"\x01" * 4 + b"\x00" * 4)   # q_proj 首字节与 base 不同

    class A:
        pass

    a = A()
    a.merged, a.base, a.spot = merged, base, True
    global EXPECT
    saved = dict(EXPECT)
    EXPECT["base_shards"] = 1
    ok &= check_merge(a)
    print("  ↑ 应 PASS（张量名一致 + q_proj 数据不同）")

    # merged 里 q_proj 与 base 相同 → adapter 没合进去 → 必须红
    with open(os.path.join(merged, "model-00001.safetensors"), "wb") as f:
        f.write(struct.pack("<Q", len(h)))
        f.write(h)
        f.write(b"\x00" * 8)
    r0 = len(rows)
    ok2 = check_merge(a)
    red = (not ok2) and any("没合进去" in d for _s, _n, _st, d in rows[r0:])
    print(f"  ↑ 未合并的样本被抓：{'YES' if red else 'NO（闸门失效！）'}")
    ok &= red

    # GGUF：造一个假头，tensor_count 对不上 → 必须红
    def gguf_write(path, n_tensor, types):
        with open(path, "wb") as f:
            f.write(b"GGUF")
            f.write(struct.pack("<I", 3))
            f.write(struct.pack("<Q", n_tensor))
            f.write(struct.pack("<Q", 0))            # 0 个 kv，省事
            for i in range(n_tensor):
                nm = f"t{i}".encode()
                f.write(struct.pack("<Q", len(nm)) + nm)
                f.write(struct.pack("<I", 1))
                f.write(struct.pack("<Q", 2))
                f.write(struct.pack("<I", types[i % len(types)]))
                f.write(struct.pack("<Q", 0))
            f.write(b"\x00" * 64)

    gp = os.path.join(tmp, "q.gguf")
    gguf_write(gp, 5, [20])
    g = gguf_scan(gp)
    print(f"  gguf_scan: tensors={g['tensor_count']} types={{(ID2NAME)}}")
    ok &= (g["tensor_count"] == 5)
    a.gguf = gp
    r0 = len(rows)
    EXPECT["base_tensors"] = 1199
    ok3 = check_gguf(a)
    red = (not ok3)
    print(f"  ↑ tensor 数不符被抓：{'YES' if red else 'NO（闸门失效！）'}")
    ok &= red

    # quant：全 IQ2_S → PASS；全 F16 → 必须红
    a.quant = gp
    EXPECT["base_tensors"] = 5
    EXPECT["quant_bytes"] = os.path.getsize(gp)      # 小样本：字节判据按实际大小设基线
    r0 = len(rows)
    ok4 = check_quant(a)
    print(f"  ↑ IQ2_S 小样本：{'PASS' if ok4 else 'FAIL（误杀）'}")
    gguf_write(gp, 5, [1])       # F16
    r0 = len(rows)
    ok5 = check_quant(a)
    red = (not ok5)
    print(f"  ↑ 未量化（F16）被抓：{'YES' if red else 'NO（闸门失效！）'}")
    ok &= red

    # act-cache：条数对 → PASS；全落 rest → 必须红
    ac = os.path.join(tmp, "act")
    for sub, n in saved["act_counts"].items():
        os.makedirs(os.path.join(ac, sub), exist_ok=True)
        for i in range(n):
            open(os.path.join(ac, sub, f"{i}.pt"), "wb").close()
    a.actcache = ac
    ok &= check_actcache(a)
    print("  ↑ act-cache 正确样本应 PASS")
    # 变体 B：全部落 rest（模拟 subsets 与 DATA 不同源）
    for sub in saved["act_counts"]:
        for i in range(saved["act_counts"][sub]):
            os.remove(os.path.join(ac, sub, f"{i}.pt"))
    for i in range(saved["act_total"]):
        open(os.path.join(ac, "rest", f"x{i}.pt"), "wb").close()
    r0 = len(rows)
    ok6 = check_actcache(a)
    red = (not ok6) and any("同源" in d for _s, _n, _st, d in rows[r0:])
    print(f"  ↑ 全落 rest 被抓：{'YES' if red else 'NO（闸门失效！）'}")
    ok &= red

    # pack：条目数对 → PASS；少 .pt → 必须红
    tp = os.path.join(tmp, "p.tar")
    with tarfile.open(tp, "w") as tf:
        for i in range(3):
            ti = tarfile.TarInfo(f"a/{i}.pt")
            ti.size = 0
            tf.addfile(ti)
    a.pack = tp
    EXPECT["pack_pt"] = 3
    EXPECT["pack_layers"] = 0
    EXPECT["pack_dirs"] = 1
    # 正确样本必须带 act-cache/（本地 local_train.ps1 硬编码这个名字）
    with tarfile.open(tp, "w") as tf:
        for d_ in ("act-cache",):
            ti = tarfile.TarInfo(d_)
            ti.type = tarfile.DIRTYPE
            tf.addfile(ti)
        for i in range(3):
            ti = tarfile.TarInfo(f"act-cache/{i}.pt")
            ti.size = 0
            tf.addfile(ti)
        for nm in ("head.safetensors", "index.json"):
            ti = tarfile.TarInfo(f"act-cache/{nm}")
            ti.size = 0
            tf.addfile(ti)
    ok &= check_pack(a)
    print("  ↑ pack 正确样本应 PASS")

    # 变异：目录名换掉且没有契约文件 → 必须红（gate 7 的 act-cache 契约自证）
    r0 = len(rows)
    tp2 = os.path.join(tmp, "p_noact.tar")
    with tarfile.open(tp2, "w") as tf:
        for i in range(3):
            ti = tarfile.TarInfo(f"act-cache-v4/{i}.pt")
            ti.size = 0
            tf.addfile(ti)
        for nm in ("head.safetensors", "index.json"):
            ti = tarfile.TarInfo(f"act-cache-v4/{nm}")
            ti.size = 0
            tf.addfile(ti)
    a.pack = tp2
    ok_noact = check_pack(a)
    red = (not ok_noact) and any("本地 local_train.ps1" in d for _s, _n, stt, d in rows[r0:])
    print(f"  ↑ 目录名不带 act-cache/ 又无契约文件 → 抓到 {red}")
    ok &= red

    # 变异：有 .act-cache-dir-name 且目录在场 → 必须 PASS（契约的逃生口）
    r1 = len(rows)
    tp3 = os.path.join(tmp, "p_contract.tar")
    with tarfile.open(tp3, "w") as tf:
        ti = tarfile.TarInfo("act-cache-v4")
        ti.type = tarfile.DIRTYPE
        tf.addfile(ti)
        for i in range(3):
            ti = tarfile.TarInfo(f"act-cache-v4/{i}.pt")
            ti.size = 0
            tf.addfile(ti)
        for nm in ("head.safetensors", "index.json"):
            ti = tarfile.TarInfo(f"act-cache-v4/{nm}")
            ti.size = 0
            tf.addfile(ti)
        blob = b"act-cache-v4"
        ti = tarfile.TarInfo(".act-cache-dir-name")
        ti.size = len(blob)
        tf.addfile(ti, io.BytesIO(blob))
    a.pack = tp3
    ok_ctr = check_pack(a)
    print(f"  ↑ 契约文件指到 act-cache-v4 且目录在场 → {ok_ctr}")
    ok &= ok_ctr

    # gate 2b：imatrix 存在/够大/不早于 gguf → PASS；把 mtime 调早 → 必须红
    imp = os.path.join(tmp, "imatrix.dat")
    with open(imp, "wb") as f:
        f.write(bytes(EXPECT["imatrix_min_bytes"] + 1024))
    a.imatrix = imp
    r2 = len(rows)
    ok_imp = check_imatrix(a)
    print(f"  ↑ imatrix 正确样本（比 gguf 新）应 PASS：{ok_imp}")
    ok &= ok_imp
    old_t = os.path.getmtime(a.gguf) - 3600
    os.utime(imp, (old_t, old_t))
    r3 = len(rows)
    ok_stale = check_imatrix(a)
    red2 = (not ok_stale) and any("不早于 bf16.gguf" in _n for _s, _n, stt, _d in rows[r3:])
    print(f"  ↑ 旧 imatrix 配新 gguf → 抓到 {red2}")
    ok &= red2

    EXPECT.update(saved)
    print(f"\nSELFTEST {'PASS' if ok else 'FAIL'}（闸门自身可信 = 每条都能红）")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="七步扩容的成功判据闸门（只读）")
    ap.add_argument("--step", default="all", help="1|2|3|5|6|7|all")
    ap.add_argument("--root", default=".", help="产物根（默认当前目录）")
    ap.add_argument("--base", default="", help="① base 模型目录（默认 <root>/base/Qwen3.8-27B）")
    ap.add_argument("--merged", default="", help="① merged 目录")
    ap.add_argument("--gguf", default="", help="② bf16 GGUF")
    ap.add_argument("--quant", default="", help="③ IQ2_S GGUF")
    ap.add_argument("--ninfer", default="", help="⑤ .ninfer 文件（可选）")
    ap.add_argument("--inspect-json", default="", help="⑤ tools.artifact.inspect 的输出")
    ap.add_argument("--actcache", default="", help="⑥ act-cache 目录")
    ap.add_argument("--pack", default="", help="⑦ tar 文件")
    ap.add_argument("--imatrix", default="", help="②b imatrix.dat（默认 <root>/imatrix.dat）")
    ap.add_argument("--spot", action="store_true",
                    help="① 抽查一个 LoRA target 张量：与 base 字节不同才算真合进去了")
    ap.add_argument("--expect-file", default="",
                    help="期望值 JSON（实测回来后写；给出的键升为硬判据）。"
                         "缺省尝试 scripts/verify-expect.json，存在就自动读")
    ap.add_argument("--set", action="append", default=[], metavar="K=V",
                    help="单项覆盖期望值（可重复），例：--set base_tensors=866")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    # 期望值来源优先级：--set > --expect-file > scripts/verify-expect.json（若存在） > 内置默认
    exp_file = a.expect_file or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "verify-expect.json")
    if os.path.isfile(exp_file):
        try:
            with open(exp_file, encoding="utf-8") as f:
                apply_expect_overrides(json.load(f), f"文件 {exp_file}")
        except Exception as e:                              # noqa: BLE001
            print(f"[FATAL] 期望值文件读不了：{exp_file}（{type(e).__name__}: {e}）")
            return 2
    elif a.expect_file:
        print(f"[FATAL] --expect-file 不存在：{a.expect_file}"
              f"（打错路径等于退回假设值，必须拦）")
        return 2
    for kv in a.set:
        if "=" not in kv:
            print(f"[FATAL] --set 需要 K=V，收到 {kv!r}")
            return 2
        k, v = kv.split("=", 1)
        try:
            val = json.loads(v)
        except Exception:                                   # noqa: BLE001
            val = v
        apply_expect_overrides({k.strip(): val}, "--set")

    if a.selftest:
        return selftest()

    r = a.root
    a.base = a.base or os.path.join(r, "base", "Qwen3.8-27B")
    a.merged = a.merged or os.path.join(r, "out", "merged")
    a.gguf = a.gguf or os.path.join(r, "out", "gguf", "model.bf16.gguf")
    a.quant = a.quant or os.path.join(r, "out", "gguf", "model.IQ2_S.gguf")
    a.actcache = a.actcache or os.path.join(r, "out", "act-cache")
    a.imatrix = a.imatrix or os.path.join(r, "imatrix.dat")
    a.pack = a.pack or os.path.join(r, "out", "pack.tar")

    steps = {"1": check_merge, "2": check_gguf, "2b": check_imatrix, "3": check_quant,
             "5": check_ninfer, "6": check_actcache, "7": check_pack}
    picked = list(steps) if a.step == "all" else [a.step.strip()]
    allok = True
    print(f"=== verify_expand  root={r}  steps={picked} ===")
    for s in picked:
        if s not in steps:
            print(f"[SKIP] 未定义步骤 {s}（④ 是 CPU 上载/卸载之类的无产物步骤？）")
            continue
        allok &= bool(steps[s](a))
    n_f = sum(1 for _s, _n, st, _d in rows if st == "FAIL")
    n_p = sum(1 for _s, _n, st, _d in rows if st == "PASS")
    print(f"\n{'PASS' if allok else 'FAIL'}：{n_p} 项通过 / {n_f} 项失败 / "
          f"{len(rows) - n_p - n_f} 项跳过")
    if a.json:
        print(json.dumps([{"step": s, "name": n, "status": st, "detail": d}
                          for s, n, st, d in rows], ensure_ascii=False, indent=2))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
