# -*- coding: utf-8 -*-
"""probe8: FLA varlen（cu_seqlens）—— packing=True 的关键；+ 无 launch-blocking 的干净计时"""
import torch, torch.nn.functional as F
from fla.modules.causal_conv1d import causal_conv1d_fwd

C, K = 1024, 4
dt = torch.bfloat16
torch.manual_seed(0)

lens = [37, 129, 250, 96]
cu = torch.tensor([0] + list(torch.cumsum(torch.tensor(lens), 0).tolist()), dtype=torch.int32, device="cuda")
T = int(cu[-1].item())

x = torch.randn(1, T, C, device="cuda", dtype=dt)
w = torch.randn(C, K, device="cuda", dtype=dt) * 0.1
b = torch.randn(C, device="cuda", dtype=dt)

with torch.no_grad():
    out = causal_conv1d_fwd(x, w, b, None, activation="silu", cu_seqlens=cu, cu_seqlens_cpu=cu.cpu())
o = out[0] if isinstance(out, tuple) else out
print("varlen out shape", tuple(o.shape))

# 参考：逐序列独立 conv1d
ref = torch.empty_like(x)
cu_l = cu.tolist()
for i in range(len(lens)):
    s, e = cu_l[i], cu_l[i + 1]
    seg = x[:, s:e, :].transpose(1, 2).contiguous()               # (1,C,L)
    r = F.conv1d(seg, w.unsqueeze(1), b, padding=K - 1, groups=C)[:, :, :e - s]
    ref[:, s:e, :] = F.silu(r).to(dt).transpose(1, 2)

d = (o.float() - ref.float()).abs()
print(f"varlen max|diff| = {d.max().item():.4e}   mean = {d.mean().item():.4e}")
# 边界：每个序列首 token 是否复位（旧状态不泄漏）
print("首 token 段 diff:", [f"{d[0, cu_l[i]:cu_l[i]+1, :].max().item():.2e}" for i in range(len(lens))])

print("\n=== 干净计时（无 CUDA_LAUNCH_BLOCKING）===")
def ref_full(x_btc, T, C, w, b):
    seg = x_btc.transpose(1, 2).contiguous()
    r = F.conv1d(seg, w.unsqueeze(1), b, padding=K - 1, groups=C)[:, :, :T]
    return F.silu(r).to(x_btc.dtype)

def bench(fn, n=50):
    for _ in range(10): fn()
    torch.cuda.synchronize()
    s = torch.cuda.Event(True); e = torch.cuda.Event(True)
    s.record()
    for _ in range(n): fn()
    e.record(); torch.cuda.synchronize()
    return s.elapsed_time(e) / n

x2 = torch.randn(4, 3424, C, device="cuda", dtype=dt)
with torch.no_grad():
    t_ref = bench(lambda: ref_full(x2, 3424, C, w, b))
    t_fla = bench(lambda: causal_conv1d_fwd(x2, w, b, None, activation="silu"))
print(f"T=3424 C=1024 ref={t_ref:.3f}ms fla={t_fla:.3f}ms speedup={t_ref/t_fla:.2f}x")
