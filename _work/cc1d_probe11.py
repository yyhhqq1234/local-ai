# -*- coding: utf-8 -*-
"""probe11: 真实布局（(B,C,T) 是 (B,T,C) 内存的视图）下零拷贝可行性"""
import torch, torch.nn.functional as F
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

for (C, T, B) in ((10240, 2048, 2), (10240, 8192, 2)):
    tc = torch.randn(B, T, C, device="cuda", dtype=DT) * 0.1      # 内存布局 (B,T,C)
    x_ct = tc.transpose(1, 2)                                     # 模型看到的是 (B,C,T) 视图
    print(f"\nC={C} T={T} B={B}  x_ct.stride()={x_ct.stride()} contiguous={x_ct.is_contiguous()}")
    w = torch.randn(C, 4, device="cuda", dtype=DT) * 0.1
    b = torch.randn(C, device="cuda", dtype=DT) * 0.1

    def ref():                                                    # transformers 参考（直接吃视图）
        out = F.conv1d(x_ct, w.unsqueeze(1), b, padding=3, groups=C)[:, :, :T]
        return F.silu(out).to(DT)

    def zero_copy():                                              # 视图进 / 视图出
        o = causal_conv1d_fwd(tc, w, b, None, activation="silu")
        o = o[0] if isinstance(o, tuple) else o
        return o.transpose(1, 2)

    def with_copy():                                              # 现在 v2 的做法
        o = causal_conv1d_fwd(x_ct.transpose(1, 2).contiguous(), w, b, None, activation="silu")
        o = o[0] if isinstance(o, tuple) else o
        return o.transpose(1, 2).contiguous()

    with torch.no_grad():
        tr, tz, tw = bench(ref), bench(zero_copy), bench(with_copy)
        # 正确性：视图进视图出 vs 参考
        d = (zero_copy().float() - ref().float()).abs().max().item()
    print(f"  ref={tr:7.3f}  zero_copy={tz:7.3f}({tr/tz:5.2f}x)  with_copy={tw:7.3f}({tr/tw:5.2f}x)  diff(zero,ref)={d:.3e}")
    print(f"  输出布局: contiguous={zero_copy().is_contiguous()} stride={zero_copy().stride()}")
