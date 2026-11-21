# -*- coding: utf-8 -*-
"""定向检查：异常工具名样本、交付物/STAGE 样本、判据占位符形态。只读，输出带 stdout utf-8。"""
import json, re, os, sys, collections, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(BASE, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']
rows = []
for f in FILES:
    for i, line in enumerate(open(os.path.join(SRC, f), encoding='utf-8')):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        a = ''.join(m.get('content') or '' for m in o['messages'] if m.get('role') == 'assistant')
        u = ''.join(m.get('content') or '' for m in o['messages'] if m.get('role') == 'user')
        rows.append((f, i, u, a))

def show(title, pred, limit=8, w=400):
    hits = [r for r in rows if pred(r[3])]
    print('\n=== %s : %d rows ===' % (title, len(hits)))
    for f, i, u, a in hits[:limit]:
        print('-- %s:%d' % (f, i))
        print(repr(a[:w]))

show('kitty_cedump', lambda a: 'kitty_cedump' in a, 4)
show('reverse_add_ bare', lambda a: re.search(r'reverse_add_(?![a-z])', a), 4)
show('STAGE', lambda a: '[STAGE]' in a, 6)
show('交付物', lambda a: '交付物' in a, 6)

# 判据 占位符形态
ph = [r for r in rows if re.search(r'判据\s*[:：]\s*(<|$|\s*$|\{|\（）|\(\)|某某|XXX)', r[3])]
print('\n=== 判据 placeholder-like : %d ===' % len(ph))
for f, i, u, a in ph[:8]:
    print('-- %s:%d %r' % (f, i, a[-160:]))

# 判据 后紧跟的内容类型统计
tails = collections.Counter()
for _, _, _, a in rows:
    for m in re.finditer(r'判据\s*[:：]\s*(.{0,12})', a):
        tails[m.group(1).strip()[:12]] += 1
print('\n=== 判据 tail top20 ===')
for k, v in tails.most_common(20):
    print('%6d %r' % (v, k))
