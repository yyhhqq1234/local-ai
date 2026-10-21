#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""probe_layout.py -- read-only layout probe for the partial-LoRA pipeline.

Prints, without loading any weight into RAM beyond headers:
  * base shard/key layout (from model.safetensors.index.json)
  * which layers/modules the LoRA adapter actually covers
  * which shards must be rewritten when merging the adapter

Used to size split_merge_layers.py before it touches 52 GiB.
"""
import collections
import json
import os
import sys

BASE = "/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B"
ADAPTER = "/root/autodl-tmp/kitty-rev/out/adapter/adapter_model.safetensors"


def main():
    idx = os.path.join(BASE, "model.safetensors.index.json")
    d = json.load(open(idx, encoding="utf-8"))
    wm = d["weight_map"]
    shards = collections.Counter(wm.values())
    print(f"[index] keys={len(wm)} shards={len(shards)}")
    print(f"[index] metadata={d.get('metadata', {})}")

    print("[index] per-shard key counts:")
    for s in sorted(shards):
        print(f"    {s:32s} {shards[s]:5d}")

    layer_keys = [k for k in wm if ".layers." in k]
    print(f"[index] layer tensor keys={len(layer_keys)}")
    per_layer = collections.Counter(int(k.split(".layers.")[1].split(".")[0]) for k in layer_keys)
    print(f"[index] layers={len(per_layer)} min_idx={min(per_layer)} max_idx={max(per_layer)}")
    print(f"[index] tensors/layer: min={min(per_layer.values())} max={max(per_layer.values())} "
          f"first5={[per_layer[i] for i in sorted(per_layer)[:5]]} "
          f"last5={[per_layer[i] for i in sorted(per_layer)[-5:]]}")

    print("[index] layer-0 keys:")
    for k in sorted(k for k in layer_keys if ".layers.0." in k):
        print("    " + k)

    print("[index] layer-60 keys:")
    for k in sorted(k for k in layer_keys if ".layers.60." in k):
        print("    " + k)

    print("[index] lm_head keys:", [k for k in wm if k.startswith("lm_head")])
    print("[index] norm keys:", [k for k in wm if "language_model.norm" in k])
    print("[index] embed keys:", [k for k in wm if "embed_tokens" in k])
    vis = [k for k in wm if k.startswith("model.visual") or "vision" in k]
    print(f"[index] visual keys={len(vis)}")
    other = [k for k in wm if not k.startswith("model.") and not k.startswith("lm_head.")]
    print(f"[index] non-model/lm_head keys={len(other)}: {other[:8]}")

    # LoRA coverage
    from safetensors import safe_open
    with safe_open(ADAPTER, framework="pt", device="cpu") as f:
        akeys = list(f.keys())
    rank = collections.Counter()
    mods = collections.Counter()
    layers = set()
    for k in akeys:
        base_key = k.split(".lora_")[0]
        parts = base_key.split(".layers.")
        if len(parts) == 2:
            layers.add(int(parts[1].split(".")[0]))
        mods[base_key.rsplit(".", 1)[-1]] += 1
        rank["lora_A" if ".lora_A." in k else ("lora_B" if ".lora_B." in k else "other")] += 1
    print(f"[adapter] keys={len(akeys)} kind={dict(rank)}")
    print(f"[adapter] layers covered: n={len(layers)} min={min(layers) if layers else None} "
          f"max={max(layers) if layers else None} all={sorted(layers) == list(range(64))}")
    print(f"[adapter] module kinds={dict(mods)}")
    print(f"[adapter] sample keys: {akeys[:4]}")
    print(f"[adapter] sample lora_B: {[k for k in akeys if 'lora_B' in k][:2]}")

    # which shards carry the adapter's target weights (upper bound for rewrite)
    targets = set()
    for k in akeys:
        bk = k.split(".lora_")[0] + ".weight"
        if bk in wm:
            targets.add(bk)
    touched = collections.Counter(wm[t] for t in targets)
    miss = len([k for k in akeys if k.split(".lora_")[0] + ".weight" not in wm])
    print(f"[merge] adapter maps to {len(targets)} base tensors across {len(touched)} shards; "
          f"unmapped={miss}")
    for s in sorted(touched):
        print(f"    {s:32s} {touched[s]:4d} tensors")
    print("PROBE_DONE")


if __name__ == "__main__":
    sys.exit(main())
