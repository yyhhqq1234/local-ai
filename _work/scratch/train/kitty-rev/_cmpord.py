from gguf import GGUFReader
from gguf.quants import dequantize
import numpy as np

def vals(path, name, n=12):
    r = GGUFReader("/root/autodl-tmp/kitty-rev/" + path)
    for t in r.tensors:
        if t.name == name:
            a = np.asarray(dequantize(t.data, t.tensor_type)).astype(np.float32).ravel()
            return t.tensor_type.name, list(t.shape), a
    return None, None, None

for name in ("blk.0.ssm_alpha.weight",):
    print("=" * 70)
    print(name)
    ty5, sh5, a5 = vals("gguf/v5-iq2s.gguf", name)
    ty6, sh6, a6 = vals("gguf/v61-iq2s-fix.gguf", name)
    print(f"  v5 : type={ty5} tshape={sh5} n={a5.size}")
    print(f"  v61: type={ty6} tshape={sh6} n={a6.size}")
    print("  v5  前12: ", np.array2string(a5[:12], precision=5))
    print("  v61 前12: ", np.array2string(a6[:12], precision=5))
    print("  v5  第5120附近:", np.array2string(a5[5116:5128], precision=5))
    print("  v61 第5120附近:", np.array2string(a6[5116:5128], precision=5))
    # 检查是否是转置关系：把 v61 按 (48,5120) reshape 后转置，再与 v5 比
    try:
        b = a6.reshape(48, 5120).T.ravel()
        d = np.abs(a5 - b)
        print(f"  假设v61需转置: |diff| max={d.max():.6g} mean={d.mean():.6g} 相同={int((d==0).sum())}/{a5.size}")
    except Exception as e:
        print("  reshape 失败:", e)
    try:
        b2 = a6.reshape(5120, 48).T.ravel()
        d2 = np.abs(a5 - b2)
        print(f"  假设 v61 按(5120,48)T: |diff| max={d2.max():.6g} mean={d2.mean():.6g} 相同={int((d2==0).sum())}/{a5.size}")
    except Exception as e:
        print("  reshape2 失败:", e)
