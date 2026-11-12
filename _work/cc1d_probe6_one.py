# -*- coding: utf-8 -*-
"""probe6_one.py  C layout dtype  -> 单独进程测 FLA update（launch failure 会毒化上下文，必须隔离）
用法: python probe6_one.py <C> <layout: b1c|bc1|flat> <dtype>
"""
import sys, torch, traceback
C = int(sys.argv[1]); layout = sys.argv[2]; dt = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[sys.argv[3]]
from fla.modules.causal_conv1d import causal_conv1d_update

K, B = 4, 2
w = (torch.randn(C, K, device="cuda", dtype=dt) * 0.1)
b = torch.randn(C, device="cuda", dtype=dt)
st = torch.randn(B, C, K, device="cuda", dtype=dt) * 0.5
x3 = torch.randn(B, C, 1, device="cuda", dtype=dt)
if layout == "b1c":
    xin = x3.transpose(1, 2).contiguous()
elif layout == "bc1":
    xin = x3
else:
    xin = x3.reshape(B, C)
try:
    out = causal_conv1d_update(xin, st, None, w, b, activation="silu")
    torch.cuda.synchronize()
    print(f"PASS C={C} layout={layout} {sys.argv[3]} out={tuple(out.shape)} finite={bool(torch.isfinite(out.float()).all())}")
except Exception as e:
    torch.cuda.synchronize() if False else None
    print(f"FAIL C={C} layout={layout} {sys.argv[3]} {type(e).__name__}: {str(e).splitlines()[0][:160]}")
