# -*- coding: utf-8 -*-
"""verify_local_pack.py -- 本地训练包体检（tar 或已解包目录，流式，不整包解压）。

为什么需要它：kittyrev-local-pack.tar（24 GiB）是 5070 Ti 上唯一能复现后训练的数据。
它坏一点点，训练不会报错——只会训出「loss 正常、能力没长」的模型（§14 静默错家族）。

检查项：
  1) 层结构：merged-layers/layer_48..63（16 个，层号连续）+ head + layers_index.json
  2) 张量：每层 safetensors 头里的张量名必须含 `layers.<N>.`（N = 文件名层号）；
     张量字节下界（默认 700 MiB，实测 766/744 两种）
  3) 哈希：每层 sha256_16 vs layers_index.json（流式算，不落盘）
  4) act-cache：11 个子目录，.pt 总数必须 == 4388（= 组内 1614 + 未分组 2774）
  5) 汇总：成员/文件总字节

用法：
  python deploy/verify_local_pack.py --tar train/lines/27b-kittyrev/local-pack/kittyrev-local-pack.tar
  python deploy/verify_local_pack.py --dir train/lines/27b-kittyrev/local-pack
  python deploy/verify_local_pack.py --tar ... --no-hash      # 跳过 sha（省几分钟）
  python deploy/verify_local_pack.py --tar ... --json logs/pack-verify.json
"""
import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tarfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LAYER_RE = re.compile(r"merged-layers/layer_(\d+)\.safetensors$")
DT = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "I64": 8, "I32": 4, "I16": 2, "I8": 1,
      "U8": 1, "BOOL": 1, "F8_E4M3": 1, "F8_E5M2": 1}
fails, warns = [], []


def parse_header(first):
    """safetensors：前 8 字节 = 头长度（LE u64），随后 JSON。first 必须 > 8+头长。"""
    hl = struct.unpack("<Q", first[:8])[0]
    if 8 + hl > len(first):
        raise ValueError(f"头长度 {hl} 超过首块 {len(first)} 字节")
    return json.loads(first[8:8 + hl].decode("utf-8"))


def tensor_stats(hdr):
    names, nbytes = [], 0
    for k, v in hdr.items():
        if k == "__metadata__":
            continue
        names.append(k)
        cnt = 1
        for d in v.get("shape", []):
            cnt *= int(d)
        nbytes += cnt * DT.get(v.get("dtype"), 0)
    return names, nbytes


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tar")
    g.add_argument("--dir")
    ap.add_argument("--no-hash", action="store_true")
    ap.add_argument("--expect-layers", type=int, default=16)
    ap.add_argument("--expect-pt", type=int, default=4388)
    ap.add_argument("--expect-act-dirs", type=int, default=11)
    ap.add_argument("--act-name", default="act-cache",
                    help="包内 act 目录必须叫这个名（默认 act-cache）。v4 云端产出叫 "
                         "act-cache-v4，pack 时用 --transform 改名；包里若仍是 act-cache-v4，"
                         "本机 local_train.ps1 会死在「缺 act-cache」")
    ap.add_argument("--min-layer-mib", type=float, default=700.0,
                    help="每层张量字节下界（实测 766/744 MiB 两种）")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    min_bytes = int(a.min_layer_mib * 2 ** 20)

    t0 = time.time()
    layers, act, index, members, total_bytes = {}, {}, None, 0, 0
    ACT_ALIASES = {a.act_name, "act-cache", "act-cache-v4"}
    alt = {}          # 别的名字下的 .pt 计数（如 act-cache-v4）

    if a.tar:
        if not os.path.isfile(a.tar):
            print(f"[FATAL] 没有这个 tar：{a.tar}")
            return 2
        print(f"[tar] {a.tar}  {os.path.getsize(a.tar)/2**30:.2f} GiB")
        with tarfile.open(a.tar, "r|") as tf:
            for m in tf:
                members += 1
                total_bytes += m.size
                n = m.name.lstrip("./")
                if not m.isfile():
                    continue
                if n.endswith("merged-layers/layers_index.json"):
                    index = json.loads(tf.extractfile(m).read().decode("utf-8"))
                    continue
                if n.endswith("merged-layers/head.safetensors") or LAYER_RE.search(n):
                    f = tf.extractfile(m)
                    first = f.read(1 << 21)          # 头一定在首 2 MiB 内
                    hdr = parse_header(first)
                    rec = {"bytes": m.size, "header": hdr}
                    if not a.no_hash:
                        h = hashlib.sha256()
                        h.update(first)
                        while True:
                            b = f.read(1 << 22)
                            if not b:
                                break
                            h.update(b)
                        rec["sha256_16"] = h.hexdigest()[:16]
                    layers[n] = rec
                elif n.endswith(".pt") and n.count("/") >= 2:
                    top, d = n.split("/")[0], n.split("/")[1]
                    if top == a.act_name:
                        act[d] = act.get(d, 0) + 1
                    elif top in ACT_ALIASES:
                        alt[top] = alt.get(top, 0) + 1
                if members % 2000 == 0:
                    print(f"  … {members} 成员 {total_bytes/2**30:.1f} GiB {time.time()-t0:.0f}s",
                          flush=True)
        src_kind = "tar"
    else:
        root = os.path.abspath(a.dir)
        ml = os.path.join(root, "merged-layers")
        if not os.path.isdir(ml):
            print(f"[FATAL] {root} 下没有 merged-layers/（还没解包？先跑 local_train 的 extract 步）")
            return 2
        src_kind = "dir"
        for f in sorted(os.listdir(ml)):
            p = os.path.join(ml, f)
            members += 1
            total_bytes += os.path.getsize(p)
            n = f"merged-layers/{f}"
            if f == "layers_index.json":
                index = json.load(open(p, encoding="utf-8"))
            elif f == "head.safetensors" or LAYER_RE.search(n):
                with open(p, "rb") as fh:
                    first = fh.read(1 << 21)
                    hdr = parse_header(first)
                    rec = {"bytes": os.path.getsize(p), "header": hdr}
                    if not a.no_hash:
                        h = hashlib.sha256()
                        h.update(first)
                        fh.seek(len(first))
                        while True:
                            b = fh.read(1 << 22)
                            if not b:
                                break
                            h.update(b)
                        rec["sha256_16"] = h.hexdigest()[:16]
                layers[n] = rec
        ac = os.path.join(root, a.act_name)
        if os.path.isdir(ac):
            for d in sorted(os.listdir(ac)):
                dp = os.path.join(ac, d)
                if os.path.isdir(dp):
                    act[d] = len([x for x in os.listdir(dp) if x.endswith(".pt")])
            members += len(act)
        else:
            for alias in sorted(ACT_ALIASES - {a.act_name}):
                ap_ = os.path.join(root, alias)
                if os.path.isdir(ap_):
                    alt[alias] = sum(len([x for x in os.listdir(os.path.join(ap_, d))
                                          if x.endswith(".pt")])
                                     for d in os.listdir(ap_)
                                     if os.path.isdir(os.path.join(ap_, d)))

    # ---------------- 1) 层结构 ----------------
    print(f"\n=== 1) 层结构（期望 {a.expect_layers}）===")
    nums = sorted(int(LAYER_RE.search(k).group(1)) for k in layers if LAYER_RE.search(k))
    print(f"  层 {len(nums)} 个：{nums[:4]}…{nums[-4:] if nums else ''}")
    if len(nums) != a.expect_layers:
        fails.append(f"层文件 {len(nums)} != {a.expect_layers}")
    if nums and nums != list(range(nums[0], nums[0] + len(nums))):
        fails.append(f"层号不连续：{nums}（中间缺层 = 打包 glob 漏了）")
    if not any(k.endswith("head.safetensors") for k in layers):
        fails.append("缺 merged-layers/head.safetensors")
    if index is None:
        fails.append("缺 merged-layers/layers_index.json（没有它就无法核哈希）")

    # ---------------- 2) 张量名 / 下界 ----------------
    print(f"\n=== 2) 张量（名含 layers.N. / 字节下界 {a.min_layer_mib:.0f} MiB）===")
    tstats = {}
    for k, v in sorted(layers.items()):
        n = int(LAYER_RE.search(k).group(1)) if LAYER_RE.search(k) else None
        if n is None:
            continue
        names, tb = tensor_stats(v["header"])
        ok_n = any(f"layers.{n}." in x for x in names)
        tstats[n] = {"tensors": len(names), "tensor_bytes": tb, "names_ok": ok_n}
        print(f"  layer_{n}: tensors={len(names):3d}  {tb/2**20:7.1f} MiB  "
              f"{'✓' if ok_n else '✗ 层号错位'}")
        if not ok_n:
            fails.append(f"layer_{n}: 张量名里没有 layers.{n}.（文件与内容不是同一层）")
        if tb < min_bytes:
            fails.append(f"layer_{n}: 张量 {tb/2**20:.0f} MiB < 下界 {min_bytes/2**20:.0f} MiB")

    # ---------------- 3) 哈希 ----------------
    if isinstance(index, dict):
        groups = index.get("groups") or {}
        by_file = {v.get("file"): v for v in groups.values() if isinstance(v, dict)}
        print(f"\n=== 3) sha256_16 vs layers_index.json（groups={len(groups)}）===")
        checked = mism = missing = 0
        for k, v in sorted(layers.items()):
            exp = by_file.get(os.path.basename(k))
            if not exp:
                missing += 1
                continue
            checked += 1
            eh = exp.get("sha256_16")
            if v.get("sha256_16") and eh and not eh.startswith(v["sha256_16"]):
                mism += 1
                fails.append(f"{os.path.basename(k)} sha {v['sha256_16']} != index {eh[:16]}")
        print(f"  已核 {checked} · 不符 {mism} · index 里没有 {missing}")
        if a.no_hash:
            warns.append("--no-hash：内容未核（只核了结构/张量/字节）")
        if missing:
            warns.append(f"{missing} 个文件在 index 里查不到（键名口径不同？需人看）")

    # ---------------- 4) act-cache ----------------
    print(f"\n=== 4) act-cache（期望目录名 {a.act_name}/ · {a.expect_act_dirs} 子目录 / {a.expect_pt} .pt）===")
    tot = sum(act.values())
    for d in sorted(act):
        print(f"  {d:16s} {act[d]:5d} .pt")
    print(f"  合计 {len(act)} 目录 / {tot} .pt")
    # 目录名硬判：本机 local_train.ps1 与 fix_pack.sh 都按 act-cache/ 写死，
    # 包里叫别的名（v4 的 act-cache-v4）就会死在「缺 act-cache」——必须在打包/体检时就拦。
    if alt:
        detail = "、".join(f"{k}/（{v} 个 .pt）" for k, v in sorted(alt.items()))
        if tot:
            warns.append(f"包里同时存在 {a.act_name}/ 与 {detail} —— 以 {a.act_name}/ 为准，另一份是垃圾")
        else:
            fails.append(f"act 目录名不对：包内是 {detail}，本机只认 {a.act_name}/。"
                         f"打包时加 --transform \"s,^<源名>/,{a.act_name}/,\"（见 pack_deliverables.sh）")
    if len(act) != a.expect_act_dirs:
        fails.append(f"act-cache 目录 {len(act)} != {a.expect_act_dirs}")
    if tot != a.expect_pt:
        fails.append(f".pt 总数 {tot} != {a.expect_pt}")
    empty = [d for d, n in act.items() if n == 0]
    if empty:
        fails.append(f"空目录：{empty}")

    # ---------------- 5) 汇总 ----------------
    print(f"\n=== 5) 汇总 ===")
    print(f"  源={src_kind} 成员 {members} · 总字节 {total_bytes/2**30:.2f} GiB · "
          f"耗时 {time.time()-t0:.0f}s")
    rep = {"src": a.tar or a.dir, "kind": src_kind, "members": members,
           "total_bytes": total_bytes, "layers": len(nums), "layer_nums": nums,
           "tensors": tstats, "act": act, "act_pt": tot, "fails": fails, "warns": warns}
    if a.json:
        os.makedirs(os.path.dirname(a.json) or ".", exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        print(f"  [write] {a.json}")
    if warns:
        print("\n[warn] " + "\n[warn] ".join(warns))
    print(f"\nPASS: {len(nums)} 层 / head / index / {tot} .pt / sha 全对"
          if not fails else f"\nFAIL: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
