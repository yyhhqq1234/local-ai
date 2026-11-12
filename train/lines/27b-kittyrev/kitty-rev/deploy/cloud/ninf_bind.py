"""ninf_bind.py —— .ninfer 头 bindings(dict: parameter -> {object}) + objects(format) → parameter→format，与参考 conversion.json 对比"""
import json
import sys
from collections import Counter


def head(path):
    with open(path, 'rb') as f:
        blob = f.read(2 << 20)
    s = blob.find(b'{')
    obj, _ = json.JSONDecoder().raw_decode(blob[s:].decode('utf-8', 'replace'))
    return obj


def map_ninfer(path):
    o = head(path)
    objs = {x['id']: x for x in o['objects']}
    m = {}
    for prm, ref in o['bindings'].items():
        oid = ref.get('object') if isinstance(ref, dict) else ref
        if oid in objs:
            m[prm] = objs[oid].get('format')
    return m


def map_conv(path):
    d = json.load(open(path, encoding='utf-8'))
    m = {}
    for it in d.get('methods', []):
        for p in it.get('parameters') or []:
            m[p] = it.get('format')
    return m


a = map_ninfer(sys.argv[1])
print('gen2 params:', len(a), '| formats:', dict(Counter(a.values())))
if len(sys.argv) > 2:
    b = map_conv(sys.argv[2])
    print('v6 params:', len(b), '| formats:', dict(Counter(b.values())))
    common = sorted(set(a) & set(b))
    print('common:', len(common))
    diffs = [(p, b[p], a[p]) for p in common if a[p] != b[p]]
    print('format diffs:', len(diffs))
    for p, f6, f2 in diffs[:40]:
        print('   %-46s v6=%-14s gen2=%s' % (p, f6, f2))
    # 按参数族聚合
    fam = Counter()
    for p, f6, f2 in diffs:
        fam[p.split('/')[2] if p.count('/') > 2 else p] += 1
    print('diff by family:', dict(fam))
    # 打印 gen2 里各族的格式分布
    print('--- gen2 format by family ---')
    f2fam = {}
    for p, f in a.items():
        k = p.split('/')[2] if p.count('/') > 2 else p
        f2fam.setdefault(k, Counter())[f] += 1
    for k in sorted(f2fam):
        print('   %-16s %s' % (k, dict(f2fam[k])))
