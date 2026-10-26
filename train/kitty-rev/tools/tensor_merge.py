#!/usr/bin/env python3
"""tensor_merge.py —— 张量级 LoRA 合并（不使用 transformers，不做模型加载）

为什么不用 merge.py / AutoModelForCausalLM：
    Qwen3.5 是混合架构（64 层，linear_attention(GDN) / full_attention 交替）。
    transformers 的参数表里没有 linear_attn.* 位，low_cpu_mem_usage=True 时不报错，
    这些张量会被建成零/随机值 → 全链闸门照样全绿，但模型输出乱码（2026-10-23 实测）。

本实现只在「命中 LoRA target 的 (layer, module)」上做 W + B@A*scale，
其余张量**原始字节复制**（不经过张量再序列化），因此：
    · linear_attn.* / embed_tokens / lm_head / *norm 与 base 逐字节相同
    · header 与 base 完全一致（同名/同 shape/同 dtype/同顺序）→ 直接复用，只改数据区

用法：
  # 自测（生成 fixture 并验证规则）
  python tools/tensor_merge.py --selftest

  # 干跑（只统计命中数，不写文件）
  python tools/tensor_merge.py --base <BASE_DIR> --adapter <ADAPTER_DIR> --out <OUT_DIR> --dry-run

  # 真跑（默认流式：每片写完+校验通过后删对应 base 片）
  python tools/tensor_merge.py --base <BASE_DIR> --adapter <ADAPTER_DIR> --out <OUT_DIR> --stream

  # 保留 base（磁盘够时）
  python tools/tensor_merge.py --base ... --adapter ... --out ... --no-stream

输出：OUT_DIR 下与 base 同名同数量的 safetensors + 复制 index.json/config.json/tokenizer*
验收：结束时打印 HIT / COPY 统计、每片 sha16、以及三条断言（见 --verify）
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import time

import numpy as np

# Windows 控制台默认 GBK，含非 ASCII 会 UnicodeEncodeError —— 自保切 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TARGET_MODULES = ("q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj")
COPY_EXTRA = ("index.json", "config.json", "generation_config.json",
              "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
              "special_tokens_map.json", "vocab.json", "merges.txt",
              "added_tokens.json", "preprocessor_config.json",
              "video_preprocessor_config.json", "processor_config.json")
CHUNK = 8 << 20  # 8 MiB 复制块


# ---------------------------------------------------------------- safetensors IO
def read_header(path):
    with open(path, "rb") as f:
        (n,) = struct.unpack("<Q", f.read(8))
        raw = f.read(n)
    hdr = json.loads(raw.decode("utf-8"))
    meta = hdr.pop("__metadata__", None)
    return hdr, raw, 8 + n, meta


def sha16_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- bf16 <-> f32
def bf16_bytes_to_f32(raw):
    u16 = np.frombuffer(raw, dtype=np.uint16)
    u32 = u16.astype(np.uint32) << 16
    return u32.view(np.float32)


def f32_to_bf16_bytes(arr):
    a = np.ascontiguousarray(arr, dtype=np.float32)
    u32 = a.view(np.uint32).copy()
    # round-to-nearest-even（与 torch bfloat16 舍入一致）
    lsb = (u32 >> 16) & np.uint32(1)
    rounded = u32 + np.uint32(0x7FFF) + lsb
    out = (rounded >> 16).astype(np.uint16)
    # 保留 NaN/Inf：指数全 1 的原值直接右移
    exp_mask = (u32 & np.uint32(0x7F800000)) == np.uint32(0x7F800000)
    if exp_mask.any():
        out[exp_mask] = (u32[exp_mask] >> 16).astype(np.uint16)
    return out.tobytes()


# ---------------------------------------------------------------- 名字解析
def parse_slot(name):
    """把任意前缀的权重名归一成 (layer_idx, 'mod.proj')；非 LoRA 目标返回 None。

    adapter: base_model.model.model.layers.0.mlp.down_proj.lora_A.weight
    base   : model.language_model.layers.0.mlp.down_proj.weight   (或已 flatten 的 model.layers.*)
    两种都能解析，前缀差异免疫。
    """
    parts = name.split(".")
    try:
        i = parts.index("layers")
    except ValueError:
        return None
    if i + 4 >= len(parts):
        return None
    try:
        idx = int(parts[i + 1])
    except ValueError:
        return None
    mod = parts[i + 2]
    proj = parts[i + 3]
    if mod not in ("self_attn", "mlp"):
        return None
    if "linear_attn" in name:
        return None
    if proj not in TARGET_MODULES:
        return None
    return (idx, f"{mod}.{proj}")


def load_adapter_lora(path):
    """读 adapter safetensors → {(layer, 'mod.proj'): (A[r,in] f32, B[out,r] f32)}"""
    hdr, raw, _, _ = read_header(path)
    with open(path, "rb") as f:
        f.seek(8 + len(raw))
        data = f.read()
    out = {}
    unrecognized = []
    for name, info in hdr.items():
        slot = parse_slot(name)
        if slot is None:
            # F6（reviewer）：adapter 里每一个张量都应当是 LoRA target A/B。
            # 认不出来 = 命名口径变了，静默丢弃会导致"部分 LoRA 没应用"而全链毫无察觉。
            unrecognized.append(name)
            continue
        off0, off1 = info["data_offsets"]
        blob = data[off0:off1]
        if info["dtype"] != "BF16":
            raise SystemExit(f"[FATAL] adapter 张量非 BF16: {name} {info['dtype']}")
        arr = bf16_bytes_to_f32(blob).reshape(info["shape"]).astype(np.float32)
        out.setdefault(slot, {})["A" if name.endswith("lora_A.weight") else "B"] = arr
    # 完整性：每 slot 必须 A+B 都在
    bad = [k for k, v in out.items() if "A" not in v or "B" not in v]
    if bad:
        raise SystemExit(f"[FATAL] adapter 有 {len(bad)} 个 slot 缺 A/B，例: {bad[:3]}")
    if unrecognized:
        raise SystemExit(f"[FATAL] adapter 有 {len(unrecognized)} 个张量无法解析成 (layer, mod.proj)："
                         f"{unrecognized[:5]} —— 命名口径变了，拒绝继续（否则 LoRA 会被静默丢弃）")
    return out


def read_adapter_scale(adapter_dir):
    p = os.path.join(adapter_dir, "adapter_config.json")
    cfg = json.load(open(p, "r", encoding="utf-8"))
    r, alpha = cfg.get("r"), cfg.get("lora_alpha")
    if not r or not alpha:
        raise SystemExit(f"[FATAL] adapter_config 缺 r/alpha: {cfg}")
    # F8（reviewer）：rsLoRA 用的缩放是 alpha/sqrt(r)，本实现按 alpha/r，混用会整体缩放错
    if cfg.get("use_rslora"):
        raise SystemExit("[FATAL] use_rslora=True：scale 规则不同（alpha/sqrt(r)），本实现不支持，拒绝继续")
    return float(alpha) / float(r), r, alpha, cfg.get("target_modules")


# ---------------------------------------------------------------- 单片合并
def merge_shard(src, dst, lora, scale, hits, copies, verbose=True):
    hdr, raw_hdr, data_start, meta = read_header(src)
    items = sorted(hdr.items(), key=lambda kv: kv[1]["data_offsets"][0])
    fsize = os.path.getsize(src)

    # 结构自检（进）
    max_end = max(v["data_offsets"][1] for v in hdr.values())
    if data_start + max_end != fsize:
        raise SystemExit(f"[FATAL] {os.path.basename(src)} 结构不符: "
                         f"{data_start}+{max_end} != {fsize}")

    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(struct.pack("<Q", len(raw_hdr)))
        fo.write(raw_hdr)          # header 原样复用（同名/同 shape/同 dtype/同序）

        def rd(pos, n):
            """pos 是**相对数据区**的偏移；文件里真实位置 = data_start + pos"""
            fi.seek(data_start + pos)
            b = fi.read(n)
            if len(b) != n:
                raise SystemExit(f"[FATAL] 短读 pos={pos} 需要 {n} 得到 {len(b)}")
            return b

        prev = 0
        for name, info in items:
            off0, off1 = info["data_offsets"]
            nbytes = off1 - off0
            if off0 > prev:                      # 间隙（对齐填充）也要保
                fo.write(rd(prev, off0 - prev))
            slot = parse_slot(name)
            if slot is not None and slot in lora:
                shp = tuple(info["shape"])
                # F5（reviewer）：base target 若不是 BF16，bf16_bytes_to_f32 会按错误位宽解释
                # → 静默写坏权重，而尺寸/有限性断言照样全过。
                if info["dtype"] != "BF16":
                    raise SystemExit(f"[FATAL] base target 张量 dtype={info['dtype']}（应为 BF16）: {name}")
                w = bf16_bytes_to_f32(rd(off0, nbytes)).reshape(shp)
                ab = lora[slot]
                A, B = ab["A"], ab["B"]
                if A.shape[1] != shp[1] or B.shape[0] != shp[0] or A.shape[0] != B.shape[1]:
                    raise SystemExit(f"[FATAL] 维度不匹配 {name}: W{shp} A{A.shape} B{B.shape}")
                delta = (B @ A) * scale
                w2 = w + delta
                if not np.isfinite(w2).all():
                    raise SystemExit(f"[FATAL] 合并后出现非有限值: {name} "
                                     f"(w_isfinite={np.isfinite(w).all()}, d_max={np.abs(delta).max():.3g})")
                fo.write(f32_to_bf16_bytes(w2))
                hits[slot] = float(np.linalg.norm(delta))
                if verbose:
                    print(f"    HIT  {name}  |delta|={hits[slot]:.4f}")
            else:
                left = nbytes
                cur = off0
                while left:
                    b = rd(cur, min(CHUNK, left))
                    fo.write(b)
                    left -= len(b)
                    cur += len(b)
                copies.append(name)
            prev = off1
        if prev < max_end:
            fo.write(rd(prev, max_end - prev))

    # 结构自检（出）
    out_size = os.path.getsize(dst)
    if out_size != fsize:
        raise SystemExit(f"[FATAL] 输出尺寸不符 {os.path.basename(dst)}: {out_size} != {fsize}")
    return out_size


# ---------------------------------------------------------------- 主流程
def run_merge(base_dir, adapter_dir, out_dir, stream, dry_run, limit_shards=None):
    scale, r, alpha, tms = read_adapter_scale(adapter_dir)
    print(f"[cfg] adapter r={r} alpha={alpha} ⇒ scale={scale}")
    print(f"[cfg] target_modules={tms}")
    lora = load_adapter_lora(os.path.join(adapter_dir, "adapter_model.safetensors"))
    print(f"[cfg] adapter slots = {len(lora)}  (每 slot A[{r},in]+B[out,{r}])")

    idx_path = os.path.join(base_dir, "model.safetensors.index.json")
    idx = json.load(open(idx_path, "r", encoding="utf-8"))
    shards = sorted(set(idx["weight_map"].values()))
    n_tensors = len(idx["weight_map"])
    print(f"[cfg] base shards = {len(shards)}, tensors(index) = {n_tensors}")
    if limit_shards:
        shards = shards[:limit_shards]
        print(f"[cfg] --limit-shards {limit_shards} ⇒ 只处理前 {len(shards)} 片（自测用）")

    # 预检：index 里每个 target 张量都能在 lora 里找到 slot
    base_slots = {}
    for n in idx["weight_map"]:
        s = parse_slot(n)
        if s is not None:
            base_slots[s] = n
    inter = set(lora) & set(base_slots)
    missing = sorted(set(lora) - set(base_slots))     # adapter 有、base 无 → LoRA 白挂，必须停
    unmerged = sorted(set(base_slots) - set(lora))    # base 有、adapter 无 → 正常（该模块没训）
    print(f"[pre] base target slots   = {len(base_slots)}")
    print(f"[pre] adapter slots       = {len(lora)}")
    print(f"[pre] 交集（会被合并）    = {len(inter)}")
    if unmerged:
        print(f"[pre] base 未挂 LoRA 的 slot = {len(unmerged)}（预期内，保持原值）: {unmerged[:4]}")
    if missing:
        raise SystemExit(f"[FATAL] adapter 有 {len(missing)} 个 slot 在 base 里找不到 → "
                         f"这些 LoRA 会被静默丢弃，拒绝继续: {missing[:5]}")
    if not inter:
        raise SystemExit("[FATAL] 交集为 0 —— adapter 与 base 的命名对不上，检查 parse_slot 规则")
    if dry_run:
        print("[dry-run] 不写文件，结束")
        return

    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    hits, copies = {}, []
    report = []
    for i, sh in enumerate(shards, 1):
        src = os.path.join(base_dir, sh)
        dst = os.path.join(out_dir, sh)
        ts = time.time()
        size = merge_shard(src, dst, lora, scale, hits, copies)
        h = sha16_file(dst)
        report.append({"shard": sh, "bytes": size, "sha16": h, "sec": round(time.time() - ts, 1)})
        print(f"[{i}/{len(shards)}] {sh}  {size:,} B  sha16={h}  {time.time()-ts:.1f}s")
        if stream:
            os.remove(src)
            print(f"        --stream: 已删 base 片 {sh}")

    # 复制旁路文件
    for fn in COPY_EXTRA:
        p = os.path.join(base_dir, fn)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(out_dir, fn))
            print(f"[copy] {fn}")

    # 三条断言
    print("\n=== 断言 ===")
    tgt_expected = len(inter)
    print(f"1) target 命中数: {len(hits)} / 期望 {tgt_expected}  "
          f"{'PASS' if len(hits) == tgt_expected else 'FAIL'}")
    zeros = [k for k, v in hits.items() if v == 0.0]
    print(f"2) delta 全非零: 零值 {len(zeros)}  "
          f"{'PASS' if not zeros else 'FAIL ' + str(zeros[:3])}")
    print(f"3) 非 target 复制张量数: {len(copies)}  (含 embed/norm/lm_head/linear_attn)")
    print(f"4) 输出片数: {len(report)} / 输入 {len(shards)}")

    rep = os.path.join(out_dir, "_merge_report.json")
    json.dump({"scale": scale, "r": r, "alpha": alpha,
               "hits": {f"L{k[0]}.{k[1]}": v for k, v in hits.items()},
               "n_copies": len(copies), "shards": report,
               "elapsed_sec": round(time.time() - t0, 1)},
              open(rep, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[report] {rep}  (total {time.time()-t0:.1f}s)")


# ---------------------------------------------------------------- 自测
def make_fixture(root, hidden=32, inter=64, r=4, n_layers=2):
    """造一个迷你 base（含 linear_attn / embed / norm / target 模块）+ 迷你 adapter"""
    import random
    random.seed(7)
    base = os.path.join(root, "base")
    ad = os.path.join(root, "adapter")
    os.makedirs(base, exist_ok=True)
    os.makedirs(ad, exist_ok=True)

    def bf(arr):
        return f32_to_bf16_bytes(np.ascontiguousarray(arr, dtype=np.float32))

    tensors = {}   # name -> (shape, dtype, bytes)
    for L in range(n_layers):
        tensors[f"model.language_model.layers.{L}.self_attn.q_proj.weight"] = ((hidden, hidden), bf(np.random.randn(hidden, hidden)))
        tensors[f"model.language_model.layers.{L}.self_attn.k_proj.weight"] = ((hidden, hidden), bf(np.random.randn(hidden, hidden)))
        tensors[f"model.language_model.layers.{L}.mlp.gate_proj.weight"] = ((inter, hidden), bf(np.random.randn(inter, hidden)))
        tensors[f"model.language_model.layers.{L}.mlp.up_proj.weight"] = ((inter, hidden), bf(np.random.randn(inter, hidden)))
        tensors[f"model.language_model.layers.{L}.mlp.down_proj.weight"] = ((hidden, inter), bf(np.random.randn(hidden, inter)))
        tensors[f"model.language_model.layers.{L}.linear_attn.in_proj_qkv.weight"] = ((hidden * 2, hidden), bf(np.random.randn(hidden * 2, hidden)))
        tensors[f"model.language_model.layers.{L}.linear_attn.out_proj.weight"] = ((hidden, hidden), bf(np.random.randn(hidden, hidden)))
        tensors[f"model.language_model.layers.{L}.input_layernorm.weight"] = ((hidden,), bf(np.random.randn(hidden)))
    tensors["model.language_model.embed_tokens.weight"] = ((128, hidden), bf(np.random.randn(128, hidden)))

    # 拆两片
    names = sorted(tensors)
    half = len(names) // 2
    shard_map = {}
    for i, chunk in enumerate([names[:half], names[half:]], 1):
        fn = f"model-{i:05d}-of-00002.safetensors"
        hdr, blobs, off = {}, [], 0
        for n in chunk:
            shp, raw = tensors[n]
            hdr[n] = {"dtype": "BF16", "shape": list(shp), "data_offsets": [off, off + len(raw)]}
            blobs.append(raw); off += len(raw)
            shard_map[n] = fn
        hb = json.dumps(hdr, separators=(",", ":")).encode()
        with open(os.path.join(base, fn), "wb") as f:
            f.write(struct.pack("<Q", len(hb))); f.write(hb); f.write(b"".join(blobs))
    json.dump({"metadata": {"total_size": 0}, "weight_map": shard_map},
              open(os.path.join(base, "model.safetensors.index.json"), "w"), indent=1)
    json.dump({"architectures": ["Qwen3_5ForCausalLM"]},
              open(os.path.join(base, "config.json"), "w"), indent=1)

    # adapter（只挂 3 个 target，缺 o_proj 与 v_proj —— 验证「base 有而 adapter 无」不报错）
    lora_specs = []
    for L in range(n_layers):
        for mod, shp in ((f"self_attn.q_proj", (hidden, hidden)),
                         (f"mlp.gate_proj", (inter, hidden)),
                         (f"mlp.down_proj", (hidden, inter))):
            lora_specs.append((L, mod, shp))
    ahdr, ablobs, aoff = {}, [], 0
    for L, mod, (o, i) in lora_specs:
        A = np.random.randn(r, i).astype(np.float32) * 0.05
        B = np.random.randn(o, r).astype(np.float32) * 0.05
        for tag, arr in (("lora_A", A), ("lora_B", B)):
            n = f"base_model.model.model.layers.{L}.{mod}.{tag}.weight"
            raw = bf(arr)
            ahdr[n] = {"dtype": "BF16", "shape": list(arr.shape), "data_offsets": [aoff, aoff + len(raw)]}
            ablobs.append(raw); aoff += len(raw)
    hb = json.dumps(ahdr, separators=(",", ":")).encode()
    with open(os.path.join(ad, "adapter_model.safetensors"), "wb") as f:
        f.write(struct.pack("<Q", len(hb))); f.write(hb); f.write(b"".join(ablobs))
    json.dump({"r": r, "lora_alpha": r * 2, "peft_type": "LORA",
               "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]},
              open(os.path.join(ad, "adapter_config.json"), "w"), indent=1)
    return base, ad, tensors, lora_specs


def selftest():
    import tempfile
    root = tempfile.mkdtemp(prefix="tmerge_selftest_")
    print(f"[selftest] fixture root = {root}")
    base, ad, tensors, specs = make_fixture(root)
    out = os.path.join(root, "merged")
    scale, r, alpha, _ = read_adapter_scale(ad)
    run_merge(base, ad, out, stream=False, dry_run=False)

    fails = []
    lora_slots = set(load_adapter_lora(os.path.join(ad, "adapter_model.safetensors")))
    # 断言 A：非 target 逐字节相等；已挂 LoRA 的 target 必须变；未挂 LoRA 的 target 必须不变
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".safetensors"):
            continue
        hdr_b, _, ds_b, _ = read_header(os.path.join(base, fn))
        hdr_m, _, ds_m, _ = read_header(os.path.join(out, fn))
        if list(hdr_b.keys()) != list(hdr_m.keys()):
            fails.append(f"{fn}: 张量名/顺序不一致")
            continue
        with open(os.path.join(base, fn), "rb") as fb, open(os.path.join(out, fn), "rb") as fm:
            for n in hdr_b:
                o0, o1 = hdr_b[n]["data_offsets"]
                fb.seek(ds_b + o0); fm.seek(ds_m + o0)
                ib, im = fb.read(o1 - o0), fm.read(o1 - o0)
                slot = parse_slot(n)
                if slot in lora_slots:
                    if ib == im:
                        fails.append(f"{fn}:{n} 是已挂 LoRA 的 target 但字节未变")
                else:
                    if ib != im:
                        fails.append(f"{fn}:{n} 非目标（无 LoRA）但字节被改动")
    # 断言 B：linear_attn 明确未被碰
    la = [n for n in tensors if "linear_attn" in n]
    print(f"[selftest] linear_attn 张量 {len(la)} 个，全部走 copy 分支")
    # 断言 C：数值正确（手算一个 slot）
    L, mod, (o, i) = specs[0]
    A = load_adapter_lora(os.path.join(ad, "adapter_model.safetensors"))[(L, mod)]["A"]
    B = load_adapter_lora(os.path.join(ad, "adapter_model.safetensors"))[(L, mod)]["B"]
    exp_delta = float(np.linalg.norm((B @ A) * scale))
    got = None
    for fn in sorted(os.listdir(out)):
        if not fn.endswith(".safetensors"):
            continue
        hdr, _, ds, _ = read_header(os.path.join(out, fn))
        for n in hdr:
            if parse_slot(n) == (L, mod):
                with open(os.path.join(out, fn), "rb") as f:
                    f.seek(ds + hdr[n]["data_offsets"][0])
                    blob = f.read(hdr[n]["data_offsets"][1] - hdr[n]["data_offsets"][0])
                Wm = bf16_bytes_to_f32(blob).reshape(hdr[n]["shape"])
                # 从 base 取原值算差
                for f2 in sorted(os.listdir(base)):
                    if not f2.endswith(".safetensors"):
                        continue
                    h2, _, d2, _ = read_header(os.path.join(base, f2))
                    if n in h2:
                        with open(os.path.join(base, f2), "rb") as f:
                            f.seek(d2 + h2[n]["data_offsets"][0])
                            bb = f.read(h2[n]["data_offsets"][1] - h2[n]["data_offsets"][0])
                        Wb = bf16_bytes_to_f32(bb).reshape(h2[n]["shape"])
                        got = float(np.linalg.norm(Wm - Wb))
    print(f"[selftest] slot {L}.{mod}: 期望 |delta|={exp_delta:.6f}  实测={got:.6f}")
    # bf16 只有 8 位尾数 ⇒ 逐元素舍入误差 ~0.4%，范数相对误差放到 2%
    if got is None or abs(got - exp_delta) > max(1e-2, exp_delta * 0.02):
        fails.append(f"数值不符: exp={exp_delta} got={got}")

    print("\n[selftest] " + ("全部通过 PASS" if not fails else f"FAIL {len(fails)} 项"))
    for f in fails:
        print("   ✗", f)
    return 0 if not fails else 1


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--adapter")
    ap.add_argument("--out")
    ap.add_argument("--stream", action="store_true", help="每片写完校验通过后删 base 片")
    ap.add_argument("--no-stream", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-shards", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not (a.base and a.adapter and a.out):
        ap.print_help()
        sys.exit(1)
    run_merge(a.base, a.adapter, a.out,
              stream=(a.stream and not a.no_stream),
              dry_run=a.dry_run, limit_shards=(a.limit_shards or None))


if __name__ == "__main__":
    main()
