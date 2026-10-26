from gguf import GGUFReader
from gguf.quants import dequantize
import numpy as np

def vals(path, name):
    r = GGUFReader("/root/autodl-tmp/kitty-rev/" + path)
    for t in r.tensors:
        if t.name == name:
            try:
                a = np.asarray(dequantize(t.data, t.tensor_type)).astype(np.float32).ravel()
            except Exception as e:
                return t.tensor_type.name, f"dequant fail {e}"
            return t.tensor_type.name, a
    return None, None

# 关键：只查 1 个张量，两个文件
name = "blk.0.ssm_alpha.weight"
ty1, a1 = vals("gguf/v61-iq2s-fix.gguf", name)
ty2, a2 = vals("gguf/v61-mtp2.gguf", name)
print(f"{name}")
print(f"  iq2s-fix: type={ty1} n={None if isinstance(a1,str) else a1.size}")
print(f"  mtp2    : type={ty2} n={None if isinstance(a2,str) else a2.size}")
if not isinstance(a1,str) and not isinstance(a2,str) and a1 is not None and a2 is not None:
    if a1.size == a2.size:
        d = np.abs(a1 - a2)
        print(f"  |iq2s - mtp2| max={d.max():.6g} mean={d.mean():.6g} 相同={int((d==0).sum())}/{a1.size}")
        print(f"  iq2s 前8: {np.array2string(a1[:8], precision=6)}")
        print(f"  mtp2 前8: {np.array2string(a2[:8], precision=6)}")
