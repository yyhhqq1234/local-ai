"""ninf_head.py —— 读 .ninfer v3 内嵌 JSON 头，输出张量/方法摘要，并与参考 conversion.json 对比"""
import json
import struct
import sys
from collections import Counter


def read_head(path):
    with open(path, 'rb') as f:
        magic = f.read(4)
        if magic != b'NINF':
            raise SystemExit('not NINF: %r' % magic)
        raw = f.read(4)
        ver = struct.unpack('<I', raw)[0]
        # 探测 JSON 长度：尝试 offset 8/12/16 的 uint32/uint64
        f.seek(0)
        blob = f.read(1 << 20)
        start = blob.find(b'{')
        # 用 json 解码器定位结尾
        dec = json.JSONDecoder()
        obj, end = dec.raw_decode(blob[start:].decode('utf-8', 'replace'))
        return ver, start, end, obj


def summarize(obj, label):
    print(f'--- {label} ---')
    print('version/name:', obj.get('name'), '| tensors:', len(obj.get('tensors', [])),
          '| objects:', len(obj.get('objects', [])))
    print('formats:', obj.get('formats'))
    ms = obj.get('methods', [])
    print('methods count:', len(ms))
    norm_methods = Counter()
    for m in ms:
        prms = m.get('parameters') or []
        if any('norm' in p for p in prms):
            norm_methods[(m.get('method'), json.dumps(m.get('method_parameters') or {}, sort_keys=True))] += 1
    print('norm methods:', dict(norm_methods))
    # 采样几条
    for m in ms[:3]:
        print('  sample:', m.get('object'), m.get('parameters'), m.get('method'), m.get('format'))
    return ms


def compare(a_ms, b_ms):
    def key(m):
        return tuple(m.get('parameters') or [])
    a = {key(m): m for m in a_ms}
    b = {key(m): m for m in b_ms}
    common = set(a) & set(b)
    print(f'--- compare: common params {len(common)} / a={len(a)} b={len(b)}')
    diff = 0
    for k in list(common)[:2000]:
        if a[k].get('method') != b[k].get('method') or a[k].get('format') != b[k].get('format'):
            diff += 1
            if diff <= 12:
                print('  DIFF', k, 'a:', a[k].get('method'), a[k].get('format'),
                      '| b:', b[k].get('method'), b[k].get('format'))
    print('method/format diffs:', diff)


if __name__ == '__main__':
    p_gen2 = sys.argv[1]
    ver, start, end, obj = read_head(p_gen2)
    print('magic NINF, version', ver, 'json at', start, 'len', end)
    ms2 = summarize(obj, 'gen2-gsqrco')
    if len(sys.argv) > 2:
        ref = json.load(open(sys.argv[2], encoding='utf-8'))
        ms6 = summarize(ref, 'v6-ref')
        compare(ms6, ms2)
