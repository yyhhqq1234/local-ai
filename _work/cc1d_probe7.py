# -*- coding: utf-8 -*-
"""probe7: FLA update 正确用法（x=(B,1,C)）+ 语义/数值/耗时对账
用法: python probe7.py <C> <dtype>   单进程只跑一个 C（隔离 launch failure）
"""
import sys, torch, torch.nn.functional as F
from fla.modules.causal_conv1d import causal_conv1d_update

C = int(sys.argv[1]); dts = sys.argv[2]
dt = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[dts]
K, B = 4, 2

w = (torch.randn(C, K, device="cuda", dtype=dt) * 0.1)
b = torch.randn(C, device="cuda", dtype=dt)
sig = torch.randn(B, C, K, device="cuda", dtype=dt) * 0.5
x_cT = torch.randn(B, C, 1, device="cuda", dtype=dt)      # transformers 布局

def ref_update(x_cT, conv_state, weight, bias, act="silu"):
    _, H, T = x_cT.shape
    sl = conv_state.shape[-1]
    new = torch.cat([conv_state, x_cT], dim=-1).to(weight.dtype)
    conv_state.copy_(new[:, :, -sl:])
    out = F.conv1d(new, weight.unsqueeze(1), bias, padding=0, groups=H)[:, :, -T:]
    return (F.silu(out) if act == "silu" else out).to(x_cT.dtype)

st_r = sig.clone()
out_r = ref_update(x_cT, st_r, w, b)

x_in = x_cT.transpose(1, 2).contiguous()                  # (B,1,C)
st_f = sig.clone()
y, cache = causal_conv1d_update(x_in, st_f, None, w, b, activation="silu")
torch.cuda.synchronize()
y_cT = y.transpose(1, 2).contiguous()                     # 回 (B,C,1)

print(f"C={C} {dts}")
print("  out  max|diff| :", (y_cT.float() - out_r.float()).abs().max().item())
print("  cache 原地更新  :", not torch.equal(st_f, sig), "| cache 与 ref 差异:",
      (st_f.float() - st_r.float()).abs().max().item())
print("  cache is 同一对象:", st_f.data_ptr() == sig.data_ptr(), "| 返回 cache ptr==sig:", cache.data_ptr() == sig.data_ptr())

def bench(fn, n=300):
    for _ in range(30): fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True); e = torch.cuda.Event(True)
    s.record()
    for _ in range(n): fn()
    e.record(); torch.cuda.synchronize()
    return s.elapsed_time(e) / n

with torch.no_grad():
    tr = bench(lambda: ref_update(x_cT, st_r, w, b))
    tf = bench(lambda: causal_conv1d_update(x_in, st_f, None, w, b, activation="silu"))
print(f"  decode 耗时: ref={tr*1000:.1f}us  fla={tf*1000:.1f}us  speedup={tr/tf:.2f}x")
