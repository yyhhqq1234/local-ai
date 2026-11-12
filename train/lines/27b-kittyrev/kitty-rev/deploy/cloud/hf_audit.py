"""hf_audit.py —— 直接读 HF safetensors（merged-*）校验 dtype 与数值尺度

判据：27B bf16 权重 mean|w| 约 0.005-0.03；若出现 1e36 / nan / 全零，说明 shard 写坏或 dtype 标错。
用法：python hf_audit.py <model_dir> [n_tensors]
"""
import json
import os
import struct
import sys

import numpy as np

d = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 6
shards = sorted(f for f in os.listdir(d) if f.endswith('.safetensors'))
print('shards:', len(shards))
rows = []
for sh in shards:
    p = os.path.join(d, sh)
    with open(p, 'rb') as f:
        n = struct.unpack('<Q', f.read(8))[0]
        hdr = json.loads(f.read(n).decode())
        base = 8 + n
        for k, v in hdr.items():
            if k == '__metadata__':
                continue
            s, e = v['data_offsets']
            dt = v['dtype']
            f.seek(base + s)
            buf = f.read(min(e - s, 1 << 22))  # 只读前 4MB 估统计
            if dt == 'BF16':
                a = (np.frombuffer(buf[:len(buf) // 2 * 2], dtype='<u2').astype(np.uint32) << 16).view(np.float32)
            elif dt == 'F32':
                a = np.frombuffer(buf[:len(buf) // 4 * 4], dtype='<f4')
            elif dt == 'F16':
                a = np.frombuffer(buf[:len(buf) // 2 * 2], dtype='<f2').astype(np.float32)
            else:
                a = np.array([], dtype=np.float32)
            if a.size:
                rows.append((float(np.abs(a).mean()), k, dt, float(np.abs(a).max())))
        if len(rows) > limit * 40:
            break

rows.sort()
print('sampled tensors:', len(rows))
print('--- 最小 8 个（mean|w|）---')
for m, k, dt, mx in rows[:8]:
    print('  %-46s %-4s mean|w|=%.3e max=%.3e' % (k, dt, m, mx))
print('--- 最大 4 个 ---')
for m, k, dt, mx in rows[-4:]:
    print('  %-46s %-4s mean|w|=%.3e max=%.3e' % (k, dt, m, mx))
import collections
print('dtype dist:', dict(collections.Counter(r[2] for r in rows)))
