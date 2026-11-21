# -*- coding: utf-8 -*-
"""量化 action 合法性 + 域外污染。只读，utf-8 stdout。"""
import json, re, os, sys, collections, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(BASE, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']
MAN = json.load(open(os.path.join(BASE, '_work/rebuild/kitty-adapt/manifest.json'), encoding='utf-8'))
MF = {m['name']: m for m in MAN}
NAMES = set(MF)

TOOLRE = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+(\*)?)')
PAIRRE = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)(\*)?\s*[`\'"]?\s*(action|op)\s*[=:]\s*[`\'"]?([A-Za-z0-9_|<>/\.]+)')

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
print('rows', len(rows))

P = collections.Counter(); BADACT = collections.Counter(); BADTOOL = collections.Counter()
rows_bad_act = set(); rows_bad_tool = set()
for f, i, u, a in rows:
    for m in PAIRRE.finditer(a):
        tool, star, kind, val = m.group(1), m.group(2), m.group(3), m.group(4)
        P[(tool, kind)] += 1
        if tool not in NAMES:
            BADTOOL[(tool, kind, val)] += 1
            rows_bad_tool.add((f, i))
            continue
        meta = MF[tool]
        if kind == 'action':
            ok = val in (meta.get('actions') or [])
        else:  # op
            ops = meta.get('ops') or []
            v = val.split('|')[0]
            ok = ('*' in ops) or (v in ops) or (val in ops)
        if not ok:
            BADACT[(tool, kind, val)] += 1
            rows_bad_act.add((f, i))

print('\n--- pairs total %d, distinct %d ---' % (sum(P.values()), len(P)))
print('rows with invalid action: %d ; rows with invalid tool: %d' % (len(rows_bad_act), len(rows_bad_tool)))
print('\n=== invalid_tool top30 ===')
for k, v in BADTOOL.most_common(30):
    print('%6d %s' % (v, k))
print('\n=== invalid_action top40 ===')
for k, v in BADACT.most_common(40):
    print('%6d %s' % (v, k))

# 域外污染
CONTAM = {
    '<tool_call>': lambda a: '<tool_call>' in a,
    'pwsh/bash': lambda a: re.search(r'"name"\s*:\s*"(pwsh|ops_bash|bash|read|write|edit)"', a) is not None,
    'LegionOptimization': lambda a: 'LegionOptimization' in a,
    'godot/dragon': lambda a: bool(re.search(r'dragon_breath|\.gd\b|project/script', a)),
    'no kitty tool at all': lambda a: not TOOLRE.search(a),
}
for name, p in CONTAM.items():
    n = sum(1 for _, _, u, a in rows if p(a))
    print('%-22s %6d (%.1f%%)' % (name, n, 100.0*n/len(rows)))
