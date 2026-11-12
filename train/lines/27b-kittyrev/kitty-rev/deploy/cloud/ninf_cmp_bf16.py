"""ninf_cmp_bf16.py —— 逐参数比较两个 .ninfer 里 bf16 张量的统计量

用途：norm/ssm_a 等非 LoRA 目标张量在两代产物里应当几乎一致；
      若 gen2 与 v6 的这些张量差异巨大（或形状/偏移错位），问题在导出/合并，而不是量化。
用法：python ninf_cmp_bf16.py <gen2.ninfer> <v6.ninfer> [最多比较条数]
"""
import json
import sys

import numpy as np


def load_head(path):
    with open(path, 'rb') as f:
        blob = f.read(4 << 20)
    s = blob.find(b'{')
    obj, _ = json.JSONDecoder().raw_decode(blob[s:].decode('utf-8', 'replace'))
    objs = {x['id']: x for x in obj['objects']}
    binds = obj['bindings']
    return obj, objs, binds


def read_bf16(path, obj_meta):
    off = int(obj_meta['offset'])
    nbytes = int(obj_meta['bytes'])
    with open(path, 'rb') as f:
        f.seek(off)
        raw = f.read(nbytes)
    a = np.frombuffer(raw, dtype='<u2').astype(np.uint32) << 16
    return a.view(np.float32)


def stats(a):
    return (float(a.mean()), float(a.std()), float(a.min()), float(a.max()), int(a.size))


g_path, v_path = sys.argv[1], sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 12

og, ogj, bg = load_head(g_path)
ov, ovj, bv = load_head(v_path)

def fmt_of(bind, objs):
    ref = bind.get('object')
    if not isinstance(ref, str):
        return None
    return (objs.get(ref) or {}).get('format')


shared = [p for p in bg if p in bv and fmt_of(bg[p], ogj) == 'bf16' and fmt_of(bv[p], ovj) == 'bf16']
print('shared bf16 params:', len(shared))
print('%-40s %-32s %-32s %s' % ('parameter', 'gen2 mean/std/min/max', 'v6 mean/std/min/max', 'cos'))
for p in shared[:limit]:
    a = read_bf16(g_path, ogj[bg[p]['object']])
    b = read_bf16(v_path, ovj[bv[p]['object']])
    sa, sb = stats(a), stats(b)
    if a.size == b.size and a.size > 0:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        cos = float(np.dot(a, b) / (na * nb)) if na > 0 and nb > 0 else float('nan')
    else:
        cos = float('nan')
    print('%-40s %-32s %-32s %s' % (
        p, '%.4g/%.4g/%.4g/%.4g' % sa[:4], '%.4g/%.4g/%.4g/%.4g' % sb[:4],
        'size %s vs %s' % (a.size, b.size) if a.size != b.size else '%.5f' % cos))
