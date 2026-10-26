from gguf import GGUFReader
from gguf.quants import dequantize
import numpy as np

def get(path, names):
    r = GGUFReader("/root/autodl-tmp/kitty-rev/" + path)
    out = {}
    for t in r.tensors:
        if t.name in names:
            try:
                arr = dequantize(t.data, t.tensor_type)
                out[t.name] = (t.tensor_type.name, np.asarray(arr).astype(np.float32).ravel())
            except Exception as e:
                out[t.name] = (t.tensor_type.name, f"dequant fail: {e}")
    return out

names = {"blk.0.ssm_alpha.weight", "blk.0.ssm_beta.weight", "blk.12.ssm_alpha.weight"}
a = get("gguf/v5-iq2s.gguf", names)
b = get("gguf/v61-iq2s-fix.gguf", names)

for n in sorted(names):
    print("=" * 70)
    print(n)
    for tag, d in (("v5(正常)", a), ("v61(坏)", b)):
        if n not in d:
            print(f"  {tag}: 缺"); continue
        ty, v = d[n]
        if isinstance(v, str):
            print(f"  {tag}: {ty} {v}"); continue
        print(f"  {tag}: type={ty} n={v.size} min={v.min():.6g} max={v.max():.6g} mean={v.mean():.6g} std={v.std():.6g}")
    if n in a and n in b and not isinstance(a[n][1], str) and not isinstance(b[n][1], str):
        va, vb = a[n][1], b[n][1]
        if va.size == vb.size:
            diff = np.abs(va - vb)
            print(f"  |v5 - v61|  max={diff.max():.6g}  mean={diff.mean():.6g}  相同元素={int((diff==0).sum())}/{va.size}")
        else:
            print(f"  尺寸不同 v5={va.size} v61={vb.size}")
