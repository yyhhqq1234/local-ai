#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t6_eval_pairing.py -- train/val 必须按"家族"配对，而不是按源名。

缺陷现象
    eval_by_cat 原本按源名配对（train 叫 re-train、val 叫 re-val → 永不成对）。
    于是每类只算到一侧：train_drop/val_drop 全是 None，passed_14_8 永远 N/A；
    §15 遗忘监控写死 ("gen","general")，也永远匹配不上 replay。
后果
    六套验收里最关键的 §14.8 判据与遗忘告警同时变成死代码，而人只看到 N/A。
正确的断言
    _src_family: re-train/re-val → re；rest/gen-val → replay；
    eval_by_cat 对 re 与 replay 家族同时给出 train_loss 与 val_loss。
如果这条 FAIL 说明什么
    配对键又漂了（回到源名），或 forget 家族被改名 —— 检查 _src_family 与 eval_by_cat。
"""
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(KITTY, "scripts"))
import torch  # noqa: E402
from train_partial_lora import MultiCache, _src_family, eval_by_cat  # noqa: E402

fails = []

# ---- 1) 家族推导 ----
CASES = [("re-train", "/x/re-train", "re"), ("re-val", "/x/re-val", "re"),
         ("rest", "/x/rest", "replay"), ("gen-val", "/x/gen-val", "replay"),
         ("gen-train", "/x/gen-train", "replay"),
         ("discipline-train", "/x/discipline-train", "discipline"),
         ("forge-train", "/x/forge-train", "forge")]
print("=== _src_family ===")
for name, root, want in CASES:
    got = _src_family(name, root)
    ok = got == want
    if not ok:
        fails.append(f"{name}/{root} → {got}，期望 {want}")
    print(f"[{'✓' if ok else '✗'}] {name:18s} {root:22s} → {got}")


# ---- 2) eval_by_cat 端到端（CPU，假 forward）----
def mk(dirpath, n, T=4, H=2):
    os.makedirs(dirpath, exist_ok=True)
    for i in range(n):
        torch.save({"hidden": torch.zeros(1, T, H, dtype=torch.bfloat16),
                    "labels": torch.randint(0, 4, (1, T), dtype=torch.long),
                    "attn": torch.ones(1, T, dtype=torch.long)},
                   os.path.join(dirpath, f"{i}.pt"))


def forward(hidden, attn, ckpt=True, ret="logits"):
    B, T, _ = hidden.shape
    return torch.zeros(B, T, 4)          # V=4 → CE = log(4) 恒定，够验证链路


tmp = tempfile.mkdtemp(prefix="rg-t6-")
try:
    mk(os.path.join(tmp, "re-train"), 2)
    mk(os.path.join(tmp, "rest"), 2)
    mk(os.path.join(tmp, "re-val"), 2)
    mk(os.path.join(tmp, "gen-val"), 2)
    train_c = MultiCache([("re-train", os.path.join(tmp, "re-train"), 4.0),
                          ("rest", os.path.join(tmp, "rest"), 1.0)], 512)
    val_c = MultiCache([("re-val", os.path.join(tmp, "re-val"), 1.0),
                        ("gen-val", os.path.join(tmp, "gen-val"), 1.0)], 512)
    a = types.SimpleNamespace(ce_chunk=2)
    out = eval_by_cat(forward, train_c, val_c, a, "cpu")
    print("\n=== eval_by_cat（假 forward）===")
    for fam in ("re", "replay"):
        rec = out.get(fam) or {}
        print(f"[{fam:7s}] {rec}")
        if "train_loss" not in rec or "val_loss" not in rec:
            fails.append(f"家族 {fam} 没配对（train={('train_loss' in rec)} "
                         f"val={('val_loss' in rec)}）")
    if "re" in out and out["re"].get("val_vs_train") is None:
        fails.append("re 家族没有 val_vs_train（配对没生效）")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: train/val 按家族配对，§14.8 的两个数都算得出来"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
