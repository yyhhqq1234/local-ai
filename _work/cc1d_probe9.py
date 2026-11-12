# -*- coding: utf-8 -*-
"""probe9: FLA autograd 路径梯度正确性（fp32/bf16，含 varlen）"""
import torch, torch.nn.functional as F
from fla.modules.causal_conv1d import causal_conv1d

def ref_fwd_grad(x, w, b, act="silu"):
    # x (B,T,C) -> 参考
    xx = x.transpose(1, 2).contiguous()
    C = xx.shape[1]
    out = F.conv1d(xx, w.unsqueeze(1), b, padding=w.shape[-1] - 1, groups=C)[:, :, :x.shape[1]]
    return (F.silu(out) if act == "silu" else out).to(x.dtype).transpose(1, 2).contiguous()

for dt in (torch.float32, torch.bfloat16):
    torch.manual_seed(0)
    B, T, C, K = 2, 64, 128, 4
    x1 = (torch.randn(B, T, C, device="cuda", dtype=dt) * 0.5).requires_grad_(True)
    w1 = (torch.randn(C, K, device="cuda", dtype=dt) * 0.1).requires_grad_(True)
    b1 = torch.randn(C, device="cuda", dtype=dt).requires_grad_(True)
    x2 = x1.detach().clone().requires_grad_(True)
    w2 = w1.detach().clone().requires_grad_(True)
    b2 = b1.detach().clone().requires_grad_(True)

    o1 = causal_conv1d(x1, w1, b1, None, activation="silu")
    o1 = o1[0] if isinstance(o1, tuple) else o1
    o2 = ref_fwd_grad(x2, w2, b2, "silu")
    g = torch.randn_like(o1.float())
    (o1.float() * g).sum().backward()
    (o2.float() * g).sum().backward()

    fwd = (o1.float() - o2.float()).abs().max().item()
    gx = (x1.grad.float() - x2.grad.float()).abs().max().item()
    gw = (w1.grad.float() - w2.grad.float()).abs().max().item()
    gb = (b1.grad.float() - b2.grad.float()).abs().max().item()
    print(f"{str(dt):16s} fwd={fwd:.3e}  gx={gx:.3e}  gw={gw:.3e}  gb={gb:.3e}")

print("\n=== 同量表（fp32, 相对误差，判断是否只是舍入） ===")
torch.manual_seed(0)
B, T, C, K = 2, 64, 128, 4
x = (torch.randn(B, T, C, device="cuda", dtype=torch.float32) * 0.5).requires_grad_(True)
w = (torch.randn(C, K, device="cuda", dtype=torch.float32) * 0.1).requires_grad_(True)
b = torch.randn(C, device="cuda", dtype=torch.float32).requires_grad_(True)
o = causal_conv1d(x, w, b, None, activation="silu")
o = o[0] if isinstance(o, tuple) else o
o.sum().backward()
print("fp32 gx |scale|:", x.grad.abs().mean().item(), "max:", x.grad.abs().max().item())
