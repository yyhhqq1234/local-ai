# -*- coding: utf-8 -*-
"""probe4: (a) 替身是否真的走了 FLA  (b) 原生 FLA vs 参考 conv1d 逐项对比  (c) update 内核正确调用形态"""
import sys, inspect, traceback, time
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
import torch, torch.nn.functional as F
import causal_conv1d as cc
from fla.modules import causal_conv1d as fm

print("fla module file:", fm.__file__)
print("_HAS_FLA:", cc._HAS_FLA, "| cc._fla_fwd is fm.fwd:", getattr(cc, "_fla_fwd", None) is fm.causal_conv1d_fwd)

print("\n=== update 源码 ===")
print(inspect.getsource(fm.causal_conv1d_update))

def ref(hs, weight, bias, act):
    _, H, T = hs.shape
    p = weight.shape[-1] - 1
    out = F.conv1d(hs.to(weight.dtype), weight.unsqueeze(1), bias, padding=p, groups=H)[:, :, :T]
    return (F.silu(out) if act == "silu" else out).to(hs.dtype)

def bench(fn, n=30):
    for _ in range(5): fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True); e = torch.cuda.Event(True)
    s.record()
    for _ in range(n): fn()
    e.record(); torch.cuda.synchronize()
    return s.elapsed_time(e) / n

print("\n=== 原生 FLA vs 参考 (c=10240, k=4) ===")
for T in (128, 512, 2048, 8192):
    hs = torch.randn(2, 10240, T, device="cuda", dtype=torch.bfloat16)
    w = (torch.randn(10240, 4, device="cuda", dtype=torch.bfloat16) * 0.1)
    b = torch.randn(10240, device="cuda", dtype=torch.bfloat16)
    with torch.no_grad():
        r = ref(hs, w, b, "silu")
        x = hs.transpose(1, 2).contiguous()
        f = fm.causal_conv1d_fwd(x, w, b, None, activation="silu")
        f = f[0] if isinstance(f, tuple) else f
        f = f.transpose(1, 2).contiguous()
        d = (f.float() - r.float()).abs().max().item()
        tr = bench(lambda: ref(hs, w, b, "silu"))
        tf = bench(lambda: fm.causal_conv1d_fwd(x, w, b, None, activation="silu"))
        tm = bench(lambda: cc.causal_conv1d_fn(hs, w, b, "silu"))
    print(f"T={T:5d} diff(fla,ref)={d:.3e} ref={tr:7.3f}ms fla={tf:7.3f}ms standin={tm:7.3f}ms  fla_speedup={tr/tf:5.2f}x")

print("\n=== decode update：语义对齐测试 ===")
# transformers 参考语义
def ref_update(hs, conv_state, weight, bias, act):
    _, H, T = hs.shape
    sl = conv_state.shape[-1]
    new = torch.cat([conv_state, hs], dim=-1).to(weight.dtype)
    conv_state.copy_(new[:, :, -sl:])
    out = F.conv1d(new, weight.unsqueeze(1), bias, padding=0, groups=H)[:, :, -T:]
    return (F.silu(out) if act == "silu" else out).to(hs.dtype)

C, K, B = 5120, 4, 2
x = torch.randn(B, 1, C, device="cuda", dtype=torch.bfloat16)
st_ref = torch.randn(B, C, K, device="cuda", dtype=torch.bfloat16)
w = (torch.randn(C, K, device="cuda", dtype=torch.bfloat16) * 0.1)
b = torch.randn(C, device="cuda", dtype=torch.bfloat16)
st_a = st_ref.clone(); st_b = st_ref.clone()
o_ref = ref_update(x, st_a, w, b, "silu")
try:
    o_fla = fm.causal_conv1d_update(x, st_b, None, w, b, activation="silu")
    print("fla update out shape", tuple(o_fla.shape), "state(fla) vs state(ref) maxdiff",
          (st_b.float() - st_a.float()).abs().max().item())
    print("out maxdiff", (o_fla.float() - o_ref.float()).abs().max().item())
    print("ref_update ms", bench(lambda: ref_update(x, st_a, w, b, "silu"), 200),
          "| fla_update ms", bench(lambda: fm.causal_conv1d_update(x, st_b, None, w, b, activation="silu"), 200))
except Exception:
    traceback.print_exc()
