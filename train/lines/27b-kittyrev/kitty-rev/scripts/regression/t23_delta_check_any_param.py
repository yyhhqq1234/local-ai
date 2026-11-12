#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t23_delta_check_any_param.py -- 梯度回流判据不许只看 params[0]。

缺陷现象
    _fit 末尾只比 params[0]：probe/||ΔW||。而 peft 的 LoRA 里 params[0] 通常是
    **lora_A**，lora_B 零初始化 → 第一步 ∂L/∂A = Bᵀ(…) = 0，A 的梯度恒为 0。
    于是真实跑 `--max-steps 1` 会打「⚠ 参数未变化 — 反向可能没通」，把人吓去查反向图。
    实测（botc 训 pack）：1 step 报 0.000000e+00；同数据 3 step 报相对变化 7.4e-01。
后果
    ① 假警报 → 误判"反向断了"；② 反过来，真断流时若 params[0] 恰好是被移动的那个，
       判据又会漏。单一参数不是判据。
正确的断言
    _delta_check(ps, p0s)：任一参数有变化 → any_moved=True 且提示 N/M；
    全部不变 → any_moved=False 且 msg 带 ⚠；空快照 → False（不崩）。
如果这条 FAIL 说明什么
    回流判据又退回"只看第一个参数"，或不再区分"部分变化/全都没变"。
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
# 可选 argv[1]：指向另一份 train_partial_lora.py（变异对照用）
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "train_partial_lora.py")
sys.path.insert(0, os.path.dirname(SCRIPT))

fails = []
try:
    tpl = importlib.import_module(os.path.splitext(os.path.basename(SCRIPT))[0])
except Exception as e:
    print(f"\nFAIL: 载入 train_partial_lora 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

if not hasattr(tpl, "_delta_check"):
    print("\nFAIL: 缺 _delta_check()（回归脚本的锚点）")
    sys.exit(1)

import torch


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


# ① 一个不动（lora_A 情形）+ 一个动了（lora_B 情形）→ 判"已回流"
a = torch.nn.Parameter(torch.full((8,), 0.1))
b = torch.nn.Parameter(torch.zeros(8))
a0 = a.detach().float().clone()
b0 = b.detach().float().clone()
with torch.no_grad():
    b.add_(1e-3)                      # 模拟 lora_B 被 AdamW 动过
msg, moved = tpl._delta_check([a, b], [a0, b0])
print(f"[msg] {msg}")
check("部分变化 → any_moved=True", moved is True, str(moved))
check("报出 1/2 有变化", "1/2 有变化" in msg, msg)

# ② 全都没动 → 必须 ⚠ 且 False（快照要取"当前"值，否则 case① 的改动会带进来）
b_now = b.detach().float().clone()
msg2, moved2 = tpl._delta_check([a, b], [a0, b_now])
print(f"[msg] {msg2}")
check("全没动 → any_moved=False", moved2 is False, str(moved2))
check("全没动 → 带 ⚠", "⚠" in msg2, msg2)

# ③ 空快照不崩
msg3, moved3 = tpl._delta_check([], [])
check("空快照不崩且 False", moved3 is False and "跳过" in msg3, msg3)

# ④ 结构：不许回到 probe = params[0]
src = open(SCRIPT, encoding="utf-8").read()
check("不再只看 params[0]", "probe = params[0]" not in src, "还在用单参数判据")

print("\nPASS: 回流判据看'任一参数动'，单步 lora_A=0 不再误报"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
