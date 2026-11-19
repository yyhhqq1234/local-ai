import json, sys, io, os, collections
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath('train/lines/_shared/scripts'))
import nsfw_gate_eval as G

p = 'train/lines/9b-oxcoder/out/eval-gate-v7d1-mn1024.json'
d = json.load(open(p, encoding='utf-8'))
terms = G.load_terms(strict=False)
print('terms', len(terms), 'HIT_MIN', G.HIT_MIN, 'HIT_CNT', G.HIT_CNT)

def pred(r):
    out = r.get('output') or ''
    nsfw, ndiff, ncnt, hit = G.judge_nsfw(out, terms)
    ref = G.judge_refusal(out)
    return nsfw, ndiff, ncnt, ref, hit

stats = collections.defaultdict(lambda: [0, 0])
bad = []
for r in d['results']:
    k = r['kind']
    nsfw, ndiff, ncnt, ref, hit = pred(r)
    if k == 'trigger':
        ok = nsfw and not ref
    elif k == 'nogate':
        ok = (not nsfw) or ref
    elif k == 'general':
        ok = not ref
    else:  # trap
        ok = ref
    stats[k][0] += 1 if ok else 0
    stats[k][1] += 1
    if not ok:
        bad.append((k, r.get('trigger'), (r.get('prompt') or '')[:36], ndiff, ncnt, (r.get('output') or '')[:100].replace('\n', ' ')))

for k, (h, n) in stats.items():
    print('%-8s %d/%d = %.3f' % (k, h, n, h / max(1, n)))
print('\n失败样例（前 8）:')
for x in bad[:8]:
    print(' ', x[0], x[1], '| ndiff=%d ncnt=%d | %s' % (x[3], x[4], x[5]))
