# -*- coding: utf-8 -*-
"""probe10: 同一进程同一张量，native FLA / 替身 / 参考 三方计时 + 谁在真的被调用"""
import sys, time
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
import torch, torch.nn.functional as F
import causal_conv1d as mine
from fla.modules.causal_conv1d import causal_conv1d_fwd

DT = torch.bfloat16

def bench(fn, iters=30, warmup=5):
    for _ in range(warmup): fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True); e = torch.cuda.Event(True)
    s.record()
    for _ in range(iters): fn()
    e.record(); torch.cuda.synchronize()
    return s.elapsed_time(e) / iters

for (C, T, B) in ((10240, 2048, 2), (10240, 8192, 2), (5120, 4096, 4)):
    hs = torch.randn(B, C, T, device="cuda", dtype=DT) * 0.1
    w2d = torch.randn(C, 4, device="cuda", dtype=DT) * 0.1
    b = torch.randn(C, device="cuda", dtype=DT) * 0.1
    x = hs.transpose(1, 2).contiguous()
    wc = w2d.reshape(C, 4).contiguous()

    def ref():
        _, H, TT = hs.shape
        out = F.conv1d(hs, w2d.unsqueeze(1), b, padding=3, groups=H)[:, :, :TT]
        return F.silu(out).to(DT)

    def fla_direct():
        o = causal_conv1d_fwd(x, wc, b, None, activation="silu")
        return (o[0] if isinstance(o, tuple) else o)

    def standin():
        return mine.causal_conv1d_fn(hs, w2d, b, "silu")

    def xfer_only():
        y = hs.transpose(1, 2).contiguous()
        return y.transpose(1, 2).contiguous()

    with torch.no_grad():
        tr = bench(ref); tf = bench(fla_direct); ts = bench(standin); tx = bench(xfer_only)
    print(f"C={C} T={T} B={B}: ref={tr:7.3f}  fla={tf:7.3f}  standin={ts:7.3f}  (仅搬运={tx:6.3f})  "
          f"fla加速={tr/tf:5.2f}x  替身加速={tr/ts:5.2f}x")
print("\ndiag:", mine.diagnostics())

print("\n=== transformers 端到端：调用一次，看是谁在跑 ===")
before = mine.diagnostics()["fwd_calls"]
from transformers.models.qwen3_5 import modeling_qwen3_5 as M
hs2 = torch.randn(1, 512, 64, device="cuda", dtype=DT) * 0.1
w2 = torch.randn(64, 4, device="cuda", dtype=DT) * 0.1
b2 = torch.randn(64, device="cuda", dtype=DT) * 0.1
with torch.no_grad():
    o = M.causal_conv1d_fn(hs2, w2, b2, activation="silu")
after = mine.diagnostics()["fwd_calls"]
print("model.causal_conv1d_fn 调用后 替身 fwd_calls:", before, "->", after, "|", "走替身" if after > before else "未走替身")
print("out", tuple(o.shape), "grad_fn", o.grad_fn)
