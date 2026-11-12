# -*- coding: utf-8 -*-
"""probe3: 定位 FLA 内核在 c=10240 下的真实异常 + 能力边界（fwd/update/autograd）"""
import sys, traceback, inspect
import torch

from fla.modules.causal_conv1d import (
    causal_conv1d_fwd, causal_conv1d, causal_conv1d_update, causal_conv1d_update_states, causal_conv1d_bwd,
)

print("== signatures ==")
for f in (causal_conv1d_fwd, causal_conv1d, causal_conv1d_update, causal_conv1d_update_states):
    try:
        print(f.__name__, inspect.signature(f))
    except Exception as e:
        print(f.__name__, "sig?", e)

print("\n== 通道数扫描 (T=512, k=4, bf16) ==")
for c in (64, 128, 512, 1024, 1920, 2048, 4096, 5120, 7168, 10240):
    x = torch.randn(2, 512, c, device="cuda", dtype=torch.bfloat16)
    w = torch.randn(c, 4, device="cuda", dtype=torch.bfloat16) * 0.1
    b = torch.randn(c, device="cuda", dtype=torch.bfloat16)
    try:
        with torch.no_grad():
            o = causal_conv1d_fwd(x, w, b, None, activation="silu")
        o = o[0] if isinstance(o, tuple) else o
        ok = bool(torch.isfinite(o.float()).all())
        print(f"c={c:6d}  OK shape={tuple(o.shape)} finite={ok}")
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        print(f"c={c:6d}  FAIL {msg[:280]}")

print("\n== update 内核 (decode, T=1) ==")
for c in (64, 5120, 10240):
    try:
        x = torch.randn(2, 1, c, device="cuda", dtype=torch.bfloat16)
        st = torch.zeros(2, c, 4, device="cuda", dtype=torch.bfloat16)
        w = torch.randn(c, 4, device="cuda", dtype=torch.bfloat16) * 0.1
        b = torch.randn(c, device="cuda", dtype=torch.bfloat16)
        st0 = st.clone()
        with torch.no_grad():
            o = causal_conv1d_update(x, st, w, b, activation="silu")
        print(f"c={c:6d}  OK out={tuple(o.shape)} state_changed={not torch.equal(st, st0)}")
    except Exception as e:
        print(f"c={c:6d}  FAIL {type(e).__name__}: {str(e)[:280]}")

print("\n== autograd wrapper 灰度 ==")
for c in (512, 10240):
    try:
        x = torch.randn(1, 128, c, device="cuda", dtype=torch.bfloat16, requires_grad=True)
        w = (torch.randn(c, 4, device="cuda", dtype=torch.bfloat16) * 0.1).requires_grad_(True)
        b = torch.randn(c, device="cuda", dtype=torch.bfloat16).requires_grad_(True)
        o = causal_conv1d(x, w, b, None, activation="silu")
        o = o[0] if isinstance(o, tuple) else o
        o.float().sum().backward()
        print(f"c={c:6d}  grad OK  gx={tuple(x.grad.shape)} gb={tuple(b.grad.shape)}")
    except Exception as e:
        print(f"c={c:6d}  grad FAIL {type(e).__name__}: {str(e)[:280]}")
