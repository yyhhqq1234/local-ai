# -*- coding: utf-8 -*-
"""解 DSH session.v4.jsonl.zstd（多帧 zstd 追加日志）-> 明文 jsonl + 索引
用法: python unzstd_multi.py <src.zstd> <out.jsonl>
"""
import sys, json, os
import zstandard as zstd

src, out = sys.argv[1], sys.argv[2]
data = open(src, 'rb').read()
print('input bytes=%d' % len(data))

# 逐帧解压（DSH 每次 append 一个独立 frame）
frames = 0
chunks = []
buf = data
while buf:
    dctx = zstd.ZstdDecompressor()
    dobj = dctx.decompressobj()
    try:
        part = dobj.decompress(buf)
    except Exception as e:
        print('frame decode error at offset %d: %s' % (len(data) - len(buf), e))
        break
    chunks.append(part)
    frames += 1
    unused = dobj.unused_data
    if not unused or len(unused) == len(buf):
        break
    buf = unused

raw = b''.join(chunks).decode('utf-8', 'replace')
print('frames=%d bytes=%d' % (frames, len(raw)))
open(out, 'w', encoding='utf-8').write(raw)

lines = [l for l in raw.split('\n') if l.strip()]
print('lines=%d' % len(lines))
hist = {}
idx = []
for i, l in enumerate(lines):
    try:
        o = json.loads(l)
    except Exception:
        hist['PARSE_FAIL'] = hist.get('PARSE_FAIL', 0) + 1
        idx.append({'i': i, 'type': 'PARSE_FAIL', 'len': len(l)})
        continue
    t = o.get('type') or (o.get('message') or {}).get('role') or '?'
    hist[t] = hist.get(t, 0) + 1
    idx.append({'i': i, 'type': t, 'len': len(l), 'keys': list(o.keys())[:10]})
print('HIST=' + json.dumps(hist, ensure_ascii=False))
json.dump(idx, open(out + '.index.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
