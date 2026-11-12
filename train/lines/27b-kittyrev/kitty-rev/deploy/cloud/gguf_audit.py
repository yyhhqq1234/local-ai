"""gguf_audit.py —— 全量审计 gguf 张量是否"全零/近零"（导出静默损坏的判据）

用法：python gguf_audit.py <gguf> [阈值=1e-6]
输出：每个张量的 mean|w|，统计近零张量清单
"""
import sys

import numpy as np
import gguf

p = sys.argv[1]
thr = float(sys.argv[2]) if len(sys.argv) > 2 else 1e-6
r = gguf.GGUFReader(p)
zero, ok, err = [], 0, []
rows = []
for t in r.tensors:
    try:
        a = np.array(t.data)
        if a.dtype == object:
            err.append((t.name, 'object dtype'))
            continue
        a = a.astype('float32')
        m = float(np.abs(a).mean())
        rows.append((m, t.name))
        if m < thr:
            zero.append((t.name, m))
        else:
            ok += 1
    except Exception as e:
        err.append((t.name, str(e)[:60]))

print('tensors:', len(r.tensors), 'ok:', ok, 'near-zero:', len(zero), 'errors:', len(err))
rows.sort()
print('--- 最小的 10 个 ---')
for m, n in rows[:10]:
    print('  %-42s mean|w|=%.3e' % (n, m))
print('--- 最大的 3 个 ---')
for m, n in rows[-3:]:
    print('  %-42s mean|w|=%.3e' % (n, m))
if zero:
    print('--- near-zero 清单（前 20）---')
    for n, m in zero[:20]:
        print('  ', n, m)
if err:
    print('--- errors（前 10）---')
    for n, e in err[:10]:
        print('  ', n, e)
