# -*- coding: utf-8 -*-
"""精测（修正正则）：action 合法性 + <tool_call> 域外污染分类。只读。"""
import json, re, os, sys, collections, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(BASE, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']
MF = {m['name']: m for m in json.load(open(os.path.join(BASE, '_work/rebuild/kitty-adapt/manifest.json'), encoding='utf-8'))}
NAMES = set(MF)

# 允许 - / . | : 以及多值用 / 分隔
PAIRRE = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)\s*[`\'"]?\s*(action|op)\s*[=:]\s*[`\'"]?([^\s`\'"，。；、）)】]+)')

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

BAD = collections.Counter(); badrows = set(); pairs = 0; placeholders = 0
for f, i, u, a in rows:
    for m in PAIRRE.finditer(a):
        tool, kind, val = m.group(1), m.group(2), m.group(3)
        if tool not in NAMES:
            continue
        pairs += 1
        # 拆多值 a/b/c
        vals = [v for v in re.split(r'[/|](?![^<]*>)', val) if v]
        if val.startswith('<') or '<' in val:
            placeholders += 1
            continue
        meta = MF[tool]
        okall = True
        for v in vals:
            if kind == 'action':
                ok = v in (meta.get('actions') or [])
            else:
                ops = meta.get('ops') or []
                ok = ('*' in ops) or (v.split('|')[0] in ops) or (v in ops)
            if not ok:
                okall = False
        if not okall:
            BAD[(tool, kind, val)] += 1
            badrows.add((f, i))

print('pairs', pairs, 'placeholder_vals', placeholders)
print('rows invalid_action', len(badrows), ' distinct patterns', len(BAD))
print('\n=== invalid patterns ===')
for k, v in BAD.most_common(60):
    print('%6d %s' % (v, k))

# <tool_call> 分类
tc = [r for r in rows if '<tool_call>' in r[3]]
print('\n<tool_call> rows', len(tc))
names = collections.Counter()
for f, i, u, a in tc:
    for m in re.finditer(r'"name"\s*:\s*"([A-Za-z0-9_]+)"', a):
        names[m.group(1)] += 1
print('tools inside tool_call:', dict(names.most_common(15)))
kitty_in_tc = sum(1 for f, i, u, a in rows if '<tool_call>' in a and re.search(r'kitty_[a-z]+|reverse_[a-z]+', a))
print('tool_call rows that also mention kitty_/reverse_:', kitty_in_tc)
