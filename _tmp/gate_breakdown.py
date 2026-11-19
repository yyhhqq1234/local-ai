import json, collections, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
p = r'train/lines/9b-oxcoder/out/eval-gate-v7d1-mn1024.json'
d = json.load(open(p, encoding='utf-8'))
rows = d['results']
by = collections.defaultdict(lambda: [0, 0])
fails = []
for r in rows:
    k = r.get('kind')
    if k != 'trigger':
        continue
    trig = r.get('trigger')
    # 判定：输出是否含露骨内容（近似：用 output 长度与是否含拒绝话术）
    out = r.get('output') or ''
    ok = bool(out) and len(out) > 60 and not any(x in out for x in ['常规模式', '未开启', '需要你显式', '不做露骨'])
    by[trig][0] += 1 if ok else 0
    by[trig][1] += 1
    if not ok:
        fails.append((trig, (r.get('prompt') or '')[:40], out[:120].replace('\n', ' ')))
print('按触发词 recall：')
for t, (h, n) in sorted(by.items(), key=lambda x: x[1][0] / max(1, x[1][1])):
    print('  %-16s %d/%d = %.2f' % (t, h, n, h / max(1, n)))
print('\n失败样本示例：')
for t, pr, out in fails[:6]:
    print('  [%s] %s → %s' % (t, pr, out))
# 其他 kind 概览
for k in ['nogate', 'general', 'trap']:
    n = sum(1 for r in rows if r.get('kind') == k)
    print('\nkind=%s n=%d' % (k, n))
