"""patch_ssm_a2.py —— 精确改写：直接按 data_offset + index*4 写，并回读同一位置校验"""
import sys
import numpy as np
import gguf

path = sys.argv[1]
name = sys.argv[2] if len(sys.argv) > 2 else 'blk.12.ssm_a'
VAL = np.float32(-1e-6)

r = gguf.GGUFReader(path)
t = next(x for x in r.tensors if x.name == name)
a = np.array(t.data).astype('float32').ravel()
bad = np.where(a >= 0)[0]
print('before:', 'n=%d nonneg=%d' % (a.size, len(bad)), 'vals', a[bad])
off = int(t.data_offset)
print('data_offset =', off, 'nbytes =', a.size * 4)

with open(path, 'r+b') as f:
    for i in bad:
        f.seek(off + int(i) * 4)
        f.write(VAL.astype('<f4').tobytes())
    f.flush()

# 回读原始字节校验（不经 gguf 缓存）
with open(path, 'rb') as f:
    for i in bad:
        f.seek(off + int(i) * 4)
        raw = f.read(4)
        v = np.frombuffer(raw, dtype='<f4')[0]
        print('  idx %d raw=%s value=%.6g' % (i, raw.hex(), v))

r2 = gguf.GGUFReader(path)
t2 = next(x for x in r2.tensors if x.name == name)
b = np.array(t2.data).astype('float32').ravel()
print('after: min=%.6g max=%.6g nonneg=%d' % (b.min(), b.max(), int((b >= 0).sum())))
print('VERDICT =', 'PASS' if int((b >= 0).sum()) == 0 else 'FAIL')
