"""patch_ssm_a.py —— 把 ssm_a 里 >=0 的退化元素改成 -1e-6（原地改写 F32 张量）

背景：gen2 的 blk.12.ssm_a 有 1 个元素是 -0.0（上游 A_log 极负 → -exp() 在 f32 下溢成 -0），
      ninfer 转换器要求 ssm_a "strictly negative"，于是 bail out。
      退化通道本身说明该通道衰减≈0，改成 -1e-6 与 v6 的数值语义一致（衰减仍≈1）。
用法：python patch_ssm_a.py <gguf> [tensor_name] [--dry]
"""
import sys

import numpy as np
import gguf

path = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else 'blk.12.ssm_a'
dry = '--dry' in sys.argv

r = gguf.GGUFReader(path)
t = next((x for x in r.tensors if x.name == name), None)
if t is None:
    raise SystemExit(f'[FATAL] tensor not found: {name}')
a = np.array(t.data).astype('float32').ravel().copy()
bad = np.where(a >= 0)[0]
print(f'[{name}] n={a.size} nonneg={len(bad)} values={a[bad]}')
if not len(bad):
    print('[skip] nothing to patch')
    raise SystemExit(0)
if dry:
    print('[dry] would patch offsets', bad.tolist())
    raise SystemExit(0)

a[bad] = np.float32(-1e-6)
off = int(t.data_offset)
print(f'[write] data_offset={off} nbytes={a.nbytes}')
with open(path, 'r+b') as f:
    f.seek(off)
    f.write(a.astype('<f4').tobytes())
print('[done] patched')
# 复核
r2 = gguf.GGUFReader(path)
t2 = next(x for x in r2.tensors if x.name == name)
b = np.array(t2.data).astype('float32').ravel()
print(f'[verify] min={b.min():.6g} max={b.max():.6g} nonneg={int((b >= 0).sum())}')
