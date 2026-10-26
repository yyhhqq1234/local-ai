from gguf import GGUFReader
from gguf.quants import dequantize
import numpy as np

def vals(path, name):
    r = GGUFReader("/root/autodl-tmp/kitty-rev/" + path)
    for t in r.tensors:
        if t.name == name:
            a = np.asarray(dequantize(t.data, t.tensor_type)).astype(np.float32).ravel()
            return t.tensor_type.name, a
    return None, None

names = ["blk.0.ssm_alpha.weight", "blk.0.mlp.gate_proj.weight", "blk.0.attn_qkv.weight",
         "blk.0.input_layernorm.weight", "blk.12.ssm_alpha.weight"]
for name in names:
    ty_b, a_b = vals("gguf/v61-merged-bf16.gguf", name)
    ty_q, a_q = vals("gguf/v61-iq2s-fix.gguf", name)
    ty_s, a_s = vals("gguf/v61-mtp2.gguf", name)
    print("=" * 74)
    print(name)
    if a_b is None:
        print("  bf16 缺"); continue
    print(f"  bf16   type={ty_b:<8} n={a_b.size}")
    if a_q is not None:
        d = np.abs(a_b - a_q) if a_b.size == a_q.size else None
        rel = (np.abs(a_b - a_q) / (np.abs(a_b) + 1e-8)).mean() if d is not None else None
        print(f"  iq2s   type={ty_q:<8} n={a_q.size}  |diff|max={d.max():.6g} mean={d.mean():.6g} rel={rel:.4g}" if d is not None else f"  iq2s   type={ty_q} n={a_q.size}  尺寸不同")
    if a_s is not None and a_q is not None and a_s.size == a_q.size:
        d2 = np.abs(a_s - a_q)
        print(f"  mtp2 vs iq2s: |diff|max={d2.max():.6g} mean={d2.mean():.6g} 相同={int((d2==0).sum())}/{a_s.size}")
