# -*- coding: utf-8 -*-
"""probe5: 抓出替身里的隐藏异常 + update 正确形态 (x=(B,C,1)/state=(B,C,K))"""
import sys, traceback
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
import torch, torch.nn.functional as F
import causal_conv1d as cc
from fla.modules.causal_conv1d import causal_conv1d_fwd, causal_conv1d_update

print("=== A 替身是否落回参考实现（booby-trap） ===")
orig_ref = cc._ref_fn
def trap(*a, **k):
    raise RuntimeError("__FALLBACK_TAKEN__")
cc._ref_fn = trap
hs = torch.randn(2, 10240, 512, device="cuda", dtype=torch.bfloat16)
w = torch.randn(10240, 4, device="cuda", dtype=torch.bfloat16) * 0.1
b = torch.randn(10240, device="cuda", dtype=torch.bfloat16)
try:
    with torch.no_grad():
        o = cc.causal_conv1d_fn(hs, w, b, "silu")
    print("stayed on FLA path, out", tuple(o.shape))
except RuntimeError as e:
    print("FALLBACK TAKEN:", e)
except Exception:
    traceback.print_exc()
cc._ref_fn = orig_ref

print("\n=== B 替身内部真实异常（复制其 FLA 分支，不吞异常） ===")
try:
    x = hs.transpose(1, 2).contiguous()
    ww = w.reshape(w.shape[0], w.shape[-1]).contiguous()
    with torch.no_grad():
        out = causal_conv1d_fwd(x, ww, b, None, activation="silu")
    out = out[0] if isinstance(out, tuple) else out
    print("OK", tuple(out.shape))
except Exception:
    traceback.print_exc()

print("\n=== C update 正确形态：x=(B,C,1) state=(B,C,K) ===")
def ref_update(x_cT, conv_state, weight, bias, act):
    # x_cT: (B, C, 1) ; conv_state: (B, C, K)
    _, H, T = x_cT.shape
    sl = conv_state.shape[-1]
    new = torch.cat([conv_state, x_cT], dim=-1).to(weight.dtype)
    conv_state.copy_(new[:, :, -sl:])
    out = F.conv1d(new, weight.unsqueeze(1), bias, padding=0, groups=H)[:, :, -T:]
    return (F.silu(out) if act == "silu" else out).to(x_cT.dtype)

C, K, B = 5120, 4, 2
sig = torch.randn(B, C, K, device="cuda", dtype=torch.bfloat16) * 0.5
w = torch.randn(C, K, device="cuda", dtype=torch.bfloat16) * 0.1
b = torch.randn(C, device="cuda", dtype=torch.bfloat16)
x = torch.randn(B, C, 1, device="cuda", dtype=torch.bfloat16)

st_r = sig.clone()
o_r = ref_update(x, st_r, w, b, "silu")

for xin_name, xin in (("(B,C,1)", x), ("(B,1,C) 转置", x.transpose(1, 2).contiguous())):
    st_f = sig.clone()
    try:
        o_f = causal_conv1d_update(xin, st_f, None, w, b, activation="silu")
        dd = (o_f.float() - o_r.float().transpose(1, 2).contiguous().float()).abs().max().item() if xin.shape == x.transpose(1,2).shape else (o_f.float() - o_r.float()).abs().max().item()
        ds = (st_f.float() - st_r.float()).abs().max().item()
        print(f"  x={xin_name:12s} out{tuple(o_f.shape)} out_diff={dd:.3e} state_diff={ds:.3e}")
    except Exception as e:
        print(f"  x={xin_name:12s} FAIL {type(e).__name__}: {str(e)[:200]}")

def bench(fn, n=200):
    for _ in range(20): fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True); e = torch.cuda.Event(True)
    s.record()
    for _ in range(n): fn()
    e.record(); torch.cuda.synchronize()
    return s.elapsed_time(e) / n

st_r2 = sig.clone(); st_f2 = sig.clone()
with torch.no_grad():
    tr = bench(lambda: ref_update(x, st_r2, w, b, "silu"))
    tf = bench(lambda: causal_conv1d_update(x.transpose(1, 2).contiguous(), st_f2, None, w, b, activation="silu"))
print(f"  update 耗时: ref={tr*1000:.1f}us  fla={tf*1000:.1f}us  speedup={tr/tf:.2f}x")
