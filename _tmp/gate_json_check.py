import json, collections, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = 'train/lines/9b-oxcoder/out/eval-gate-v7d1-mn1024.json'
d = json.load(open(p, encoding='utf-8'))
print('params', d.get('params'))
for k in ['trigger', 'nogate', 'general', 'trap']:
    rows = [r for r in d['results'] if r.get('kind') == k]
    nsfw = sum(1 for r in rows if r.get('nsfw'))
    ref = sum(1 for r in rows if r.get('refusal'))
    print('%-8s n=%d nsfw=%d refusal=%d' % (k, len(rows), nsfw, ref))
print('\ntrigger 逐条 (nsfw, hits, 输出前 60):')
for r in d['results']:
    if r.get('kind') != 'trigger':
        continue
    print('  %-14s nsfw=%-5s hits=%-2d refusal=%-5s | %s' % (
        r.get('trigger'), r.get('nsfw'), r.get('hits', 0), r.get('refusal'),
        (r.get('output') or '')[:60].replace('\n', ' ')))
