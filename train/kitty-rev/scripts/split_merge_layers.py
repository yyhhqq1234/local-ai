#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""split_merge_layers.py -- merge a LoRA adapter into a 27B checkpoint *and*
split it into one file per layer, shard by shard, under a tight disk budget.

Why this exists
    The cloud box has ~98 GiB free.  base 52 GiB + merged 52 GiB does not fit
    next to a full 54 GiB `merge.py` output plus a 16 GiB `.ninfer`.  So we never
    materialise a second copy of the whole model: we read ONE shard, apply the
    LoRA delta to the tensors that need it, write the results into per-group
    part files, then unlink that shard immediately.  Peak disk = parts (<= full
    model) + one in-flight shard; peak RSS = one layer + one tensor.

Key naming (measured on this checkpoint, do not guess)
    base      model.language_model.layers.<N>.<module>.weight
    adapter   base_model.model.model.layers.<N>.<module>.lora_{A,B}.weight
              ^^^^^^^^^^^^^^^ peft wrapper prefix; and `model.layers` here
              corresponds to `model.language_model.layers` in the base.
    `mtp.layers.0.*` also matches a naive `layers.(\\d+)` regex -- it must be
    routed to `other`, never mixed into layer_00.

Usage
    # 1) free, instant, no writes -- always run this first
    python split_merge_layers.py --src base/Qwen3.8-27B --adapter out/adapter \
        --out merged-layers --dry-run

    # 2) real run (rewrites 52 GiB; source shards are deleted as they are consumed)
    python split_merge_layers.py --src base/Qwen3.8-27B --adapter out/adapter \
        --out merged-layers

Output
    <out>/embed.safetensors
    <out>/layer_00.safetensors ... layer_63.safetensors
    <out>/head.safetensors        (language_model.norm + lm_head, NOT tied)
    <out>/visual.safetensors      (vision tower; text-only training may delete it)
    <out>/other.safetensors       (mtp.*, rotary embeds, anything unmapped)
    <out>/layers_index.json       (keys / bytes / sha256_16 / part files per group)
"""
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import sys
import time

import torch
from safetensors import safe_open
from safetensors.torch import save_file

MTX = re.compile(r"^mtp\.")
LAYERS = re.compile(r"^(?P<prefix>.+?\.layers\.)(?P<idx>\d+)\.")
LORA_KEY = re.compile(r"^(?:base_model\.model\.)?model\.layers\.(?P<idx>\d+)\.(?P<mod>.+)\.lora_(?P<ab>[AB])\.weight$")


def human(n):
    if n >= 2 ** 30:
        return f"{n / 2 ** 30:.2f} GiB"
    return f"{n / 2 ** 20:.1f} MiB"


def detect_layer_prefix(keys):
    """Return the text prefix up to but excluding the layer index, e.g.
    'model.language_model.layers.' -- never 'mtp.layers.'."""
    cand = collections.Counter()
    for k in keys:
        if MTX.match(k):
            continue
        m = LAYERS.match(k)
        if m:
            cand[m.group("prefix")] += 1
    if not cand:
        return None
    return cand.most_common(1)[0][0]


def make_classifier(layer_prefix):
    def classify(key):
        if MTX.match(key):
            return "other", None
        if key.startswith("model.visual.") or ".vision_tower." in key or key.startswith("model.vision"):
            return "visual", None
        m = LAYERS.match(key)
        if m and m.group("prefix") == layer_prefix:
            return "layer", int(m.group("idx"))
        if ".embed_tokens" in key:
            return "embed", None
        if key.startswith("lm_head.") or ".language_model.norm." in key:
            return "head", None
        return "other", None
    return classify


def group_name(group, idx):
    return f"layer_{idx:02d}" if group == "layer" else group


def load_adapter(adapter_dir):
    """-> ({(layer, mod): (A, B)}, meta). 152 MiB total, safe to hold in RAM."""
    cfg_path = os.path.join(adapter_dir, "adapter_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    st = os.path.join(adapter_dir, "adapter_model.safetensors")
    if not os.path.exists(st):
        raise SystemExit(f"[FATAL] 缺少 {st}")

    pairs = {}
    with safe_open(st, framework="pt", device="cpu") as f:
        keys = list(f.keys())
        for k in keys:
            m = LORA_KEY.match(k)
            if not m:
                continue
            idx, mod, ab = int(m.group("idx")), m.group("mod"), m.group("ab")
            pairs.setdefault((idx, mod), {})[ab] = f.get_tensor(k)
    lora = {}
    bad = 0
    for (idx, mod), d in pairs.items():
        if "A" in d and "B" in d:
            lora[(idx, mod)] = (d["A"], d["B"])
        else:
            bad += 1
    r = int(cfg.get("r") or 16)
    alpha = int(cfg.get("lora_alpha") or 2 * r)
    meta = {"r": r, "alpha": alpha, "scale": float(alpha) / float(r),
            "targets": len(lora), "incomplete_pairs": bad,
            "raw_keys": len(keys), "unparsed": len(keys) - sum(len(v) for v in pairs.values())}
    return lora, meta


def merge_one(weight, A, B, scale):
    """W += (B @ A) * scale, computed in fp32, cast back to the original dtype."""
    dt = weight.dtype
    w = weight.to(torch.float32)
    delta = torch.matmul(B.to(torch.float32), A.to(torch.float32))
    w.add_(delta, alpha=scale)
    return w.to(dt).contiguous()


def sha256_16(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser(description="merge LoRA + split a 27B checkpoint into per-layer files")
    ap.add_argument("--src", required=True, help="原始 base 目录（含 *.safetensors + index.json）")
    ap.add_argument("--adapter", required=True, help="LoRA adapter 目录（含 adapter_model.safetensors）")
    ap.add_argument("--out", required=True, help="输出目录（per-layer safetensors）")
    ap.add_argument("--dry-run", action="store_true", help="只统计，不落盘、不删源")
    ap.add_argument("--keep-shards", action="store_true",
                    help="保留源 shard（磁盘不够别用：峰值会翻倍）")
    ap.add_argument("--limit-layers", type=int, default=0, help="只输出前 N 层（调试用，0=全部）")
    ap.add_argument("--max-group-bytes", type=int, default=2684354560,
                    help="单个最终文件字节上限，超出则分片（默认 2.5 GiB：embed/head 各 2.37 GiB 刚好单文件，"
                         "phase2 峰值 ≈ 2.4 GiB 仍 < 3 GiB 目标）")
    ap.add_argument("--no-hash", action="store_true", help="跳过 sha256（省 52 GiB 读）")
    ap.add_argument("--no-lora", action="store_true", help="不合并 adapter，只拆层")
    a = ap.parse_args()

    t0 = time.time()
    src = os.path.abspath(a.src)
    out = os.path.abspath(a.out)

    shards = sorted(f for f in os.listdir(src) if f.endswith(".safetensors"))
    if not shards:
        raise SystemExit(f"[FATAL] {src} 下没有 .safetensors")
    idx_path = None
    for name in os.listdir(src):
        if name.endswith(".safetensors.index.json"):
            idx_path = os.path.join(src, name)
            break
    if idx_path:
        wm = json.load(open(idx_path, encoding="utf-8"))["weight_map"]
    else:
        wm = None
        print("[warn] 没有 index.json，将退化为逐 shard 扫描（仍正确，只是慢）")

    all_keys = list(wm.keys()) if wm else None
    if all_keys is None:
        all_keys, wm = [], {}
        for sh in shards:
            with safe_open(os.path.join(src, sh), framework="pt", device="cpu") as f:
                for k in f.keys():
                    all_keys.append(k)
                    wm[k] = sh

    layer_prefix = detect_layer_prefix(all_keys)
    if not layer_prefix:
        raise SystemExit("[FATAL] 找不到 layer 张量前缀")
    classify = make_classifier(layer_prefix)
    print(f"[scan] shards={len(shards)} keys={len(all_keys)} layer_prefix={layer_prefix!r}")

    # ---- plan: group -> keys, plus which shards touch which groups ----------
    group_keys = collections.defaultdict(list)
    shard_of = {}
    shard_groups = collections.defaultdict(set)
    for k in all_keys:
        g, i = classify(k)
        if g == "layer" and a.limit_layers and i >= a.limit_layers:
            continue
        gk = group_name(g, i)
        group_keys[gk].append(k)
        shard_of[k] = wm[k]
        shard_groups[wm[k]].add(gk)
    n_layers = sum(1 for g in group_keys if g.startswith("layer_"))

    # ---- lora ---------------------------------------------------------------
    lora, lmeta = ({}, {"r": 0, "alpha": 0, "scale": 0.0, "targets": 0,
                        "incomplete_pairs": 0, "raw_keys": 0, "unparsed": 0})
    if not a.no_lora:
        lora, lmeta = load_adapter(os.path.abspath(a.adapter))
    print(f"[lora] r={lmeta['r']} alpha={lmeta['alpha']} scale={lmeta['scale']:.4f} "
          f"targets={lmeta['targets']} pairs={lmeta['raw_keys']} "
          f"unprocessed={lmeta['unparsed']} incomplete={lmeta['incomplete_pairs']}")

    # adapter target -> base key, using the measured prefix mapping
    def base_key_for(idx, mod):
        return f"{layer_prefix}{idx}.{mod}.weight"

    hit_keys = set()
    miss = []
    for (idx, mod) in lora:
        bk = base_key_for(idx, mod)
        if bk in wm:
            hit_keys.add(bk)
        else:
            miss.append(bk)
    print(f"[lora] mapped to base tensors: {len(hit_keys)}   unmapped: {len(miss)}")
    if miss:
        print(f"[lora] 例: {miss[:3]}")
        if len(miss) > 0.5 * max(1, len(lora)):
            raise SystemExit("[FATAL] 超过一半 LoRA 目标对不上 base 键名 —— 前缀映射错了，拒绝继续")

    # ---- byte accounting: exact, from safetensors headers only -------------
    # file layout: 8-byte little-endian header length, then JSON {key: {dtype,shape,data_offsets}}
    tens_bytes = {}
    total_src = 0
    for sh in shards:
        p = os.path.join(src, sh)
        total_src += os.path.getsize(p)
        with open(p, "rb") as fh:
            n = int.from_bytes(fh.read(8), "little")
            hdr = json.loads(fh.read(n))
        for k, v in hdr.items():
            if k == "__metadata__":
                continue
            off = v.get("data_offsets")
            if off:
                tens_bytes[k] = int(off[1]) - int(off[0])

    per_group_keys = {g: len(v) for g, v in group_keys.items()}
    group_bytes = {g: sum(tens_bytes.get(k, 0) for k in keys) for g, keys in group_keys.items()}

    print(f"[plan] layers={n_layers} groups={len(group_keys)} "
          f"src_bytes={human(total_src)} keep_shards={a.keep_shards}")
    for g in sorted(group_keys, key=lambda x: (not x.startswith("layer_"), x)):
        if g.startswith("layer_") and g not in ("layer_00", "layer_47", "layer_48", "layer_63"):
            continue
        print(f"    {g:12s} keys={per_group_keys[g]:4d} {human(group_bytes[g]):>9s}")

    if a.dry_run:
        layer_groups = [g for g in group_keys if g.startswith("layer_")]
        layer_bytes = sum(group_bytes[g] for g in layer_groups)
        nonlayer = {g: (per_group_keys[g], group_bytes[g]) for g in group_keys if not g.startswith("layer_")}
        free = shutil.disk_usage(out if os.path.isdir(out) else os.path.dirname(out) or ".").free
        print(f"[dry-run] 层数={n_layers}（layer_00..layer_{n_layers - 1:02d}） 层字节合计={human(layer_bytes)}"
              f"  平均每层={human(layer_bytes / max(1, n_layers))}")
        for g, (kn, gb) in sorted(nonlayer.items()):
            print(f"[dry-run] 非层组 {g:8s} keys={kn:4d} {human(gb):>9s}"
                  f"{'  ← 分片输出（超过 max_group_bytes）' if gb > a.max_group_bytes else ''}")
        print(f"[dry-run] 预计输出合计 ≈ {human(total_src)}（{n_layers} 层 + {len(nonlayer)} 个非层组）")
        print(f"[dry-run] LoRA 需重写张量 {len(hit_keys)} 个（占 adapter 目标 {len(lora)}）")
        print(f"[dry-run] 目标盘剩余 {human(free)}；"
              f"{'保留源 shard → 峰值 ≈ ' + human(2 * total_src) if a.keep_shards else '删除源 shard → 峰值 ≈ ' + human(total_src)}")
        if not a.keep_shards and free < total_src * 1.05:
            print("[dry-run][WARN] 剩余空间不足以完成（parts 与最终文件会短暂共存），先清理磁盘")
        print(f"[dry-run] 未落盘、未删除任何文件，用时 {time.time() - t0:.1f}s")
        return

    # ---- real run -----------------------------------------------------------
    if os.path.exists(out):
        if os.listdir(out) and not os.path.exists(os.path.join(out, ".parts")):
            raise SystemExit(f"[FATAL] {out} 非空且不是本脚本的中间态，拒绝覆盖")
    parts_dir = os.path.join(out, ".parts")
    os.makedirs(parts_dir, exist_ok=True)

    merged_n = 0
    consumed = []
    for n, sh in enumerate(shards, 1):
        sh_path = os.path.join(src, sh)
        groups_here = sorted(shard_groups.get(sh, ()))
        print(f"[shard {n}/{len(shards)}] {sh}  groups={len(groups_here)}")
        for g in groups_here:
            want = [k for k in group_keys[g] if shard_of[k] == sh]
            if not want:
                continue
            buf = {}
            with safe_open(sh_path, framework="pt", device="cpu") as f:
                for k in want:
                    t = f.get_tensor(k)
                    if k in hit_keys:
                        idx = int(k[len(layer_prefix):].split(".")[0])
                        mod = k[len(layer_prefix):].split(".", 1)[1][:-len(".weight")]
                        A, B = lora[(idx, mod)]
                        t = merge_one(t, A, B, lmeta["scale"])
                        merged_n += 1
                    else:
                        t = t.contiguous()
                    buf[k] = t
            dst = os.path.join(parts_dir, f"{g}__{sh}")
            save_file(buf, dst, metadata={"format": "pt"})
            print(f"    part {g:12s} keys={len(buf):4d} → {os.path.basename(dst)}")
            del buf
        if not a.keep_shards:
            os.unlink(sh_path)
            consumed.append(sh)
            print(f"    [unlink] {sh}（已消费）")

    # ---- phase 2: concat parts into final group files ----------------------
    print(f"[phase2] 合并 parts → 最终文件（max_group_bytes={human(a.max_group_bytes)}）")
    report = {}
    for g in sorted(group_keys):
        parts = sorted(p for p in os.listdir(parts_dir) if p.startswith(g + "__"))
        if not parts:
            continue
        buf, cur, seq, files = {}, 0, 0, []
        def flush():
            nonlocal buf, cur, seq
            if not buf:
                return
            tmp = os.path.join(parts_dir, f".flush_{g}_{seq:02d}.safetensors")
            save_file(buf, tmp, metadata={"format": "pt"})
            files.append(tmp)
            buf, cur = {}, 0
            seq += 1
        for p in parts:
            with safe_open(os.path.join(parts_dir, p), framework="pt", device="cpu") as f:
                for k in f.keys():
                    t = f.get_tensor(k)
                    buf[k] = t
                    cur += t.numel() * t.element_size()
            os.unlink(os.path.join(parts_dir, p))
            if cur >= a.max_group_bytes:
                flush()
        flush()
        final = []
        for seq_i, tmp in enumerate(files):
            target = os.path.join(out, f"{g}.safetensors" if len(files) == 1
                                  else f"{g}.{seq_i:02d}.safetensors")
            os.replace(tmp, target)
            final.append(os.path.basename(target))
        nbytes = sum(os.path.getsize(os.path.join(out, f)) for f in final)
        keys_n = per_group_keys[g]
        digest = "-" if a.no_hash else "+".join(sha256_16(os.path.join(out, f)) for f in final)[:32]
        report[g] = {"files": final, "keys": keys_n, "bytes": nbytes, "sha256_16": digest}
        print(f"[write] {g:12s} files={len(final)} keys={keys_n:4d} {human(nbytes):>9s} {digest}")

    shutil.rmtree(parts_dir, ignore_errors=True)

    # ship the metadata the local trainer needs (config/tokenizer are tiny and
    # otherwise the downstream train_partial_lora.py cannot build its skeleton)
    copied = []
    for name in ("config.json", "generation_config.json", "tokenizer.json",
                 "tokenizer_config.json", "chat_template.jinja",
                 "preprocessor_config.json", "video_preprocessor_config.json"):
        s = os.path.join(src, name)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(out, name))
            copied.append(name)
    print(f"[copy] 元数据 {len(copied)} 个 → {out}: {copied}")

    meta = {"src": src, "adapter": os.path.abspath(a.adapter), "out": out,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "layer_prefix": layer_prefix, "n_layers": n_layers,
            "lora": dict(lmeta, merged_tensors=merged_n, mapped=len(hit_keys)),
            "shards_consumed": len(consumed),
            "totals": {"groups": len(report), "keys": sum(v["keys"] for v in report.values()),
                       "bytes": sum(v["bytes"] for v in report.values())},
            "groups": report}
    with open(os.path.join(out, "layers_index.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(report)} 组 → {out}  用时 {time.time() - t0:.1f}s  "
          f"merged_tensors={merged_n}  consumed_shards={len(consumed)}")
    if a.keep_shards:
        print("[warn] --keep-shards：源 shard 未删除，磁盘占用翻倍")


if __name__ == "__main__":
    sys.exit(main())
