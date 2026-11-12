import json, os
OUT = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out'
for f in ['kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer', 'oxcoder9b-merged.ninfer']:
    p = os.path.join(OUT, f)
    j = json.load(open(p + '.conversion.json', encoding='utf-8'))
    print('=' * 60)
    print(f)
    print('  size      :', round(os.path.getsize(p) / 2**30, 2), 'GiB')
    print('  objects   :', j.get('objects'), ' payload:', round(j.get('payload_bytes', 0) / 2**30, 2), 'GiB')
    print('  seconds   :', round(j.get('seconds', 0), 1))
    print('  device    :', j.get('device'), ' rows/chunk:', j.get('rows_per_chunk'))
    fmt = j.get('formats')
    if isinstance(fmt, dict):
        print('  formats   :', json.dumps(fmt, ensure_ascii=False, sort_keys=True))
    elif isinstance(fmt, list):
        print('  formats   :', json.dumps(fmt, ensure_ascii=False)[:300])
    comps = j.get('components')
    if isinstance(comps, dict):
        print('  components:', list(comps.keys()))
    prov = j.get('provenance') or {}
    print('  provenance:', json.dumps(prov, ensure_ascii=False)[:300])
