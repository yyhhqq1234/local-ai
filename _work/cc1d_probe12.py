# -*- coding: utf-8 -*-
"""probe12: decode update 在模型里为什么慢（是否每次重新特化/编译）"""
import torch, time
from fla.modules.causal_conv1d import causal_conv1d_update

DT = torch.bfloat16
C, K = 1024, 4          # 小模型 GDN conv_dim 量级

w = torch.randn(C, K, device="cuda", dtype=DT) * 0.1
b = torch.randn(C, device="cuda", dtype=DT) * 0.1

def one(fresh_alloc=True, view=False):
    if fresh_alloc:
        x = torch.randn(1, 1, C, device="cuda", dtype=DT)      # 每轮新分配（模型里就是这样）
        st = torch.randn(1, C, K, device="cuda", dtype=DT)
    else:
        x = one.x; st = one.st
    if view:
        xin = x.view(1, C, 1).transpose(1, 2)                  # (1,1,C) 视图，stride 走非标准
    else:
        xin = x
    return causal_conv1d_update(xin, st, None, w, b, activation="silu")

one.x = torch.randn(1, 1, C, device="cuda", dtype=DT)
one.st = torch.randn(1, C, K, device="cuda", dtype=DT)

for tag, kw in (("固定张量", dict(fresh_alloc=False)),
                ("每轮新分配", dict(fresh_alloc=True)),
                ("每轮新分配+非连续视图", dict(fresh_alloc=True, view=True))):
    with torch.no_grad():
        for _ in range(5):
            one(**kw)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(50):
            one(**kw)
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / 50 * 1000
    print(f"  {tag:22s} {dt:8.3f} ms/次")

print("\n=== 每轮重新编译？看 triton cache 目录数量变化 ===")
import triton, os, glob
root = os.path.join(os.path.expanduser("~"), ".triton", "cache")
n0 = len(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
with torch.no_grad():
    for _ in range(20):
        one(fresh_alloc=True)
torch.cuda.synchronize()
n1 = len(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
print(f"triton cache 文件数 {n0} -> {n1}")
