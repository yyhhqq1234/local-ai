import subprocess, json, os, sys
PY = r'D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\python.exe'
CWD = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-master'
OUT = r'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out'
files = ['kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer', 'oxcoder9b-merged.ninfer']

for f in files:
    p = os.path.join(OUT, f)
    print('=' * 70)
    print(f, round(os.path.getsize(p) / 2**30, 2), 'GiB')
    r = subprocess.run([PY, '-m', 'tools.artifact.inspect', p, '--json'],
                       cwd=CWD, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        print('inspect failed:', r.stderr[:300]); continue
    d = json.loads(r.stdout)
    comps = list((d.get('components') or {}).keys())
    print('components:', comps)
    print('objects:', d.get('objects'), 'tensors:', d.get('tensors'))
    # 从对象里统计 format
    r2 = subprocess.run([PY, '-m', 'tools.artifact.inspect', p, '--objects'],
                        cwd=CWD, capture_output=True, text=True, encoding='utf-8')
    txt = r2.stdout
    import re
    fmts = {}
    for m in re.finditer(r'\b(q\d+_g\d+|q\d+|bf16|fp32|fp16|nvfp4|fp8_\w+)\b', txt):
        fmts[m.group(1)] = fmts.get(m.group(1), 0) + 1
    print('format mentions:', dict(sorted(fmts.items(), key=lambda kv: -kv[1])[:8]))
    cj = p + '.conversion.json'
    if os.path.exists(cj):
        with open(cj, encoding='utf-8') as fh:
            meta = json.load(fh)
        print('provenance:', json.dumps({k: meta.get(k) for k in ('converter', 'recipe', 'sources', 'components')}, ensure_ascii=False)[:400])
    else:
        print('provenance: (no conversion.json)')
