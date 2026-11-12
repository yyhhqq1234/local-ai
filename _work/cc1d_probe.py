# -*- coding: utf-8 -*-
"""causal_conv1d 现状探针：环境 / 替身模块 / FLA-Triton 路径 / transformers 取核链路"""
import os, sys, traceback

sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")

def hr(t):
    print("\n" + "=" * 70 + "\n# " + t + "\n" + "=" * 70)

hr("0 环境")
import torch
print("torch", torch.__version__, "cuda_avail", torch.cuda.is_available())
print("device", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu")

hr("1 替身模块 import")
import causal_conv1d as cc
print("module file:", cc.__file__)
print("_HAS_FLA  :", getattr(cc, "_HAS_FLA", None))

hr("2 FLA 直接调用（Triton 路径）")
try:
    from fla.modules.causal_conv1d import causal_conv1d_fwd
    B, T, H, W = 2, 64, 64, 4
    x = torch.randn(B, T, H, device="cuda", dtype=torch.bfloat16)
    w = torch.randn(H, W, device="cuda", dtype=torch.bfloat16) * 0.1
    b = torch.randn(H, device="cuda", dtype=torch.bfloat16)
    out = causal_conv1d_fwd(x, w, b, None, activation="silu")
    o = out[0] if isinstance(out, tuple) else out
    print("FLA OK shape", tuple(o.shape), "finite", bool(torch.isfinite(o.float()).all()))
except Exception:
    print("FLA FAILED:")
    traceback.print_exc()

hr("3 替身 fn 端到端 vs 参考（含加速比）")
import torch.nn.functional as F
def ref(hs, weight, bias, act):
    _, H, T = hs.shape
    p = weight.shape[-1] - 1
    out = F.conv1d(hs.to(weight.dtype), weight.unsqueeze(1), bias, padding=p, groups=H)[:, :, :T]
    return (F.silu(out) if act == "silu" else out).to(hs.dtype)

for T in (64, 512, 2048):
    hs = torch.randn(2, 4096, T, device="cuda", dtype=torch.bfloat16)
    w = (torch.randn(4096, 1, 4, device="cuda", dtype=torch.bfloat16) * 0.1)
    bb = torch.randn(4096, device="cuda", dtype=torch.bfloat16)
    with torch.no_grad():
        a = cc.causal_conv1d_fn(hs, w, bb, "silu")
        r = ref(hs, w, bb, "silu")
        d = (a.float() - r.float()).abs().max().item()
        def bench(fn, n=20):
            for _ in range(5): fn()
            torch.cuda.synchronize()
            s = torch.cuda.Event(True); e = torch.cuda.Event(True)
            s.record()
            for _ in range(n): fn()
            e.record(); torch.cuda.synchronize()
            return s.elapsed_time(e) / n
        t_ref = bench(lambda: ref(hs, w, bb, "silu"))
        t_my = bench(lambda: cc.causal_conv1d_fn(hs, w, bb, "silu"))
    print(f"T={T:5d}  max|diff|={d:.3e}  ref={t_ref:.3f}ms  mine={t_my:.3f}ms  speedup={t_ref/t_my:.2f}x")

hr("4 transformers 取核链路")
try:
    import transformers
    print("transformers", transformers.__version__)
    from transformers.integrations.hub_kernels import use_kernel_func_from_hub_with_fallback as dec
    src = open(dec.__code__.co_filename, encoding="utf-8").read().splitlines()
    print("decorator file:", dec.__code__.co_filename, "line", dec.__code__.co_firstlineno)
    print("\n".join(f"{i+1:5d}| {l}" for i, l in enumerate(src[dec.__code__.co_firstlineno - 1: dec.__code__.co_firstlineno + 70])))
except Exception:
    traceback.print_exc()

hr("5 kernels 包状态")
try:
    import kernels
    print("kernels", getattr(kernels, "__version__", "?"))
except Exception as e:
    print("kernels import fail:", e)
