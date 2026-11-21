# -*- coding: utf-8 -*-
"""量化：精确重复规模、模板痕迹命中量、工具名/action 异常规模。只读。"""
import json, re, os, collections, hashlib

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(BASE, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']

def norm(s):
    return ' '.join((s or '').strip().lower().split())

rows = []
for f in FILES:
    for i, line in enumerate(open(os.path.join(SRC, f), encoding='utf-8')):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        msgs = o['messages']
        u = ''.join(m.get('content') or '' for m in msgs if m.get('role') == 'user')
        a = ''.join(m.get('content') or '' for m in msgs if m.get('role') == 'assistant')
        rows.append((f, i, u, a))
print('rows', len(rows))

# 1 精确重复（user+assistant 规范化）
h = collections.Counter(hashlib.sha256((norm(u) + '\x00' + norm(a)).encode()).hexdigest() for _, _, u, a in rows)
print('exact_dup_groups', sum(1 for v in h.values() if v > 1), 'exact_dup_rows', sum(v for v in h.values() if v > 1))
hu = collections.Counter(hashlib.sha256(norm(u).encode()).hexdigest() for _, _, u, a in rows)
print('same_user_groups', sum(1 for v in hu.values() if v > 1), 'same_user_rows', sum(v for v in hu.values() if v > 1), 'max_user_repeat', max(hu.values()))

# 2 模板命中
PATS = {
    'STAGE': re.compile(r'\[STAGE\]'),
    '判据': re.compile(r'判据\s*[:：]'),
    '交付物': re.compile(r'交付物\s*[:：]|交付物'),
    '收口行': re.compile(r'当前\s*[:：].{0,40}结果\s*[:：].{0,40}下一步\s*[:：]'),
    '记得': re.compile(r'记得\s*[:：]'),
    '好的明白': re.compile(r'^\s*(好的|明白了?|收到|OK|ok)[。.!！]?\s*$'),
}
for name, p in PATS.items():
    n_a = sum(1 for _, _, u, a in rows if p.search(a))
    n_u = sum(1 for _, _, u, a in rows if p.search(u))
    print('%-8s assistant=%5d (%4.1f%%)  user=%5d' % (name, n_a, 100.0*n_a/len(rows), n_u))

# 3 短回答 & 无工具
MAN = os.path.join(BASE, '_work/rebuild/kitty-adapt/manifest.json')
NAMES = set(m['name'] for m in json.load(open(MAN, encoding='utf-8')))
TOOLRE = re.compile(r'\b((?:kitty|reverse)_[a-z0-9_*]+)')
short_no_tool = sum(1 for _, _, u, a in rows if len(a.strip()) < 20 and not TOOLRE.search(a))
print('short(<20)_no_tool', short_no_tool)
print('assistant_empty', sum(1 for _, _, u, a in rows if not a.strip()))
unk = collections.Counter()
for _, _, u, a in rows:
    for t in TOOLRE.findall(a):
        if t.endswith('*'):
            continue
        if t not in NAMES:
            unk[t] += 1
print('unknown_tool_hits', dict(unk))

# 4 user 复述问题（assistant 是否只是重复 user）
restate = 0
for _, _, u, a in rows:
    ua, aa = norm(u), norm(a)
    if aa and len(aa) < 120 and (aa in ua or (len(aa) > 12 and ua.endswith(aa[:40]))):
        restate += 1
print('possible_restate', restate)
