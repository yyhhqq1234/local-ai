"""ninf_diff.py —— 从 .ninfer 内嵌头取 object→(parameters, format)，与参考 conversion.json 的 methods 对比"""
import json
import sys
from collections import Counter


def head_obj(path):
    with open(path, 'rb') as f:
        blob = f.read(1 << 20)
    start = blob.find(b'{')
    obj, end = json.JSONDecoder().raw_decode(blob[start:].decode('utf-8', 'replace'))
    return obj


def gen2_map(path):
    o = head_obj(path)
    print('gen2 header keys:', sorted(o.keys())[:20])
    objs = o.get('objects') or []
    print('objects:', len(objs), 'sample:', json.dumps(objs[0], ensure_ascii=False)[:400] if objs else None)
    m = {}
    for it in objs:
        prms = it.get('parameters') or it.get('params') or []
        if isinstance(prms, str):
            prms = [prms]
        fmt = it.get('format')
        for p in prms:
            m[p] = fmt
    return m


def ref_map(path):
    d = json.load(open(path, encoding='utf-8'))
    m = {}
    for it in d.get('methods', []):
        fmt = it.get('format')
        for p in it.get('parameters') or []:
            m[p] = fmt
    return m


if __name__ == '__main__':
    a = gen2_map(sys.argv[1])
    b = ref_map(sys.argv[2])
    print('gen2 params:', len(a), '| v6 params:', len(b))
    common = sorted(set(a) & set(b))
    print('common:', len(common))
    diff = [(p, b[p], a[p]) for p in common if a[p] != b[p]]
    print('format diffs:', len(diff))
    for p, f6, f2 in diff[:25]:
        print('   %-46s v6=%-12s gen2=%s' % (p, f6, f2))
    only2 = sorted(set(a) - set(b))[:10]
    only6 = sorted(set(b) - set(a))[:10]
    print('only in gen2 (sample):', only2)
    print('only in v6 (sample):', only6)
