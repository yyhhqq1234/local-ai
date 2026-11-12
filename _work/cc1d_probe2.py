# -*- coding: utf-8 -*-
"""probe2: 修正权重形状(2D) + 装饰器取核链路 + FLA backward/update 能力 + 模型级 prefill/decode 基准"""
import os, sys, time, traceback, logging

sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
import torch, torch.nn.functional as F

def hr(t): print("\n" + "=" * 70 + "\n# " + t + "\n" + "=" * 70)

hr("1 装饰器解析链路")
try:
    from transformers.integrations.hub_kernels import use_kernel_func_from_hub_with_fallback as dec
    import inspect
    src = inspect.getsource(dec)
    print(src[:3000])
except Exception:
    traceback.print_exc()

hr("2 FLA 内核能力面")
try:
    import fla.modules.causal_conv1d as fm
    names = [n for n in dir(fm) if "conv1d" in n]
    print("fla.modules.causal_conv1d:", names)
    for n in names:
        o = getattr(fm, n)
        print("  ", n, "->", type(o).__name__)
except Exception:
    traceback.print_exc()

hr("3 替身 fn vs 参考（正确权重 2D）+ 加速比")
import causal_conv1d as cc
def ref(hs, weight, bias, act):
    _, H, T = hs.shape
    p = weight.shape[-1] - 1
    out = F.conv1d(hs.to(weight.dtype), weight.unsqueeze(1), bias, padding=p, groups=H)[:, :, :T]
    return (F.silu(out) if act == "silu" else out).to(hs.dtype)

def bench(fn, n=20):
    for _ in range(5): fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True); e = torch.cuda.Event(True)
    s.record()
    for _ in range(n): fn()
    e.record(); torch.cuda.synchronize()
    return s.elapsed_time(e) / n

for T in (64, 512, 2048, 8192):
    hs = torch.randn(2, 10240, T, device="cuda", dtype=torch.bfloat16)
    w = (torch.randn(10240, 4, device="cuda", dtype=torch.bfloat16) * 0.1)
    bb = torch.randn(10240, device="cuda", dtype=torch.bfloat16)
    with torch.no_grad():
        a = cc.causal_conv1d_fn(hs, w, bb, "silu")
        r = ref(hs, w, bb, "silu")
        d = (a.float() - r.float()).abs().max().item()
        tr = bench(lambda: ref(hs, w, bb, "silu"))
        tm = bench(lambda: cc.causal_conv1d_fn(hs, w, bb, "silu"))
    print(f"T={T:5d} c=10240 max|diff|={d:.3e} ref={tr:7.3f}ms mine={tm:7.3f}ms speedup={tr/tm:5.2f}x")

hr("4 FLA 训练路径（grad）可用性")
try:
    from fla.modules.causal_conv1d import causal_conv1d_fwd
    x = torch.randn(1, 128, 64, device="cuda", dtype=torch.bfloat16, requires_grad=True)
    w = torch.randn(64, 4, device="cuda", dtype=torch.bfloat16, requires_grad=True)
    b = torch.randn(64, device="cuda", dtype=torch.bfloat16, requires_grad=True)
    o = causal_conv1d_fwd(x, w, b, None, activation="silu")
    o = o[0] if isinstance(o, tuple) else o
    o.float().sum().backward()
    print("FLA backward OK  x.grad", tuple(x.grad.shape), "w.grad", tuple(w.grad.shape))
except Exception:
    print("FLA backward FAILED:"); traceback.print_exc()

hr("5 transformers 端到端：模型里 conv1d 走的是哪条")
try:
    from transformers.models.qwen3_5 import modeling_qwen3_5 as M
    print("causal_conv1d_fn in model ->", M.causal_conv1d_fn)
    print("wrapped?", hasattr(M.causal_conv1d_fn, "__wrapped__"))
    print("verdict: 若上面函数 __module__ 是 causal_conv1d 说明走替身/FLA")
except Exception:
    traceback.print_exc()
