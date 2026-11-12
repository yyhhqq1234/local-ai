#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_fake_actcache.py -- generate fake activation-cache samples for smoke tests.

Produces the exact tensor contract that precompute_activations.py writes, so
train_partial_lora.py can be smoke-tested on a laptop without touching a 27B
checkpoint:

    <out>/<i>.pt = {
        "hidden": bf16 [1, T, H],
        "labels": int64 [1, T]   (some positions -100, mimicking masked/padded),
        "attn":   int64 [1, T],
        "n": T, "src": i, "mask": "fake"
    }

Usage
    python gen_fake_actcache.py --out /tmp/fake-cache --n 3 --ctx 64 --hidden 256 --vocab 1024
"""
import argparse
import os

import torch


def main():
    ap = argparse.ArgumentParser(description="fake act-cache for smoke tests")
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--ctx", type=int, default=64)
    ap.add_argument("--hidden", type=int, default=256)
    ap.add_argument("--vocab", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    os.makedirs(a.out, exist_ok=True)
    for i in range(a.n):
        T = max(8, a.ctx - i * 3)
        hidden = torch.randn(1, T, a.hidden, dtype=torch.float32).to(torch.bfloat16)
        labels = torch.randint(0, a.vocab, (1, T), dtype=torch.long)
        labels[0, : T // 4] = -100          # pretend the prompt part is masked
        attn = torch.ones(1, T, dtype=torch.long)
        torch.save({"hidden": hidden, "labels": labels, "attn": attn,
                    "n": T, "src": i, "mask": "fake"},
                   os.path.join(a.out, f"{i}.pt"))
        print(f"[fake] {i}.pt hidden={tuple(hidden.shape)} labels={tuple(labels.shape)} T={T}")
    print(f"[done] {a.n} 条 → {a.out}")


if __name__ == "__main__":
    main()
