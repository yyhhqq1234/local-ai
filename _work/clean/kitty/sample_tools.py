# -*- coding: utf-8 -*-
"""工具名/action 出现形态采样：抽取 assistant 中 kitty_*/reverse_* 附近上下文。只读。"""
import json, re, os, collections

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(BASE, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']
MF = os.path.join(BASE, '_work/rebuild/kitty-adapt/manifest.json')
mf = {m['name']: m for m in json.load(open(MF, encoding='utf-8'))}
NAMES = set(mf)

TOOLRE = re.compile(r'\b((?:kitty|reverse)_[a-z0-9_]+)')
ACTRE = re.compile(r'(?:action|op|via|mode)\s*[=:]\s*`?([A-Za-z0-9_|<>]+)')

names = collections.Counter(); unknown = collections.Counter()
acts = collections.Counter(); act_by_tool = collections.defaultdict(collections.Counter)
ctx = collections.Counter()
no_tool = 0; total = 0
for f in FILES:
    for line in open(os.path.join(SRC, f), encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        total += 1
        o = json.loads(line)
        asst = ''.join(m.get('content') or '' for m in o['messages'] if m.get('role') == 'assistant')
        found = TOOLRE.findall(asst)
        if not found:
            no_tool += 1
        for t in found:
            names[t] += 1
            if t not in NAMES:
                unknown[t] += 1
        for m in ACTRE.finditer(asst):
            a = m.group(1)
            # 定位最近的前置工具名
            pre = TOOLRE.findall(asst[max(0, m.start()-160):m.start()])
            tool = pre[-1] if pre else '?'
            acts[a] += 1
            act_by_tool[tool][a] += 1
        # 采样形态
        for m in re.finditer(r'.{0,25}(?:kitty|reverse)_[a-z0-9_]+.{0,45}', asst):
            ctx[m.group(0).replace('\n', ' ')] += 1

print('total rows', total, 'rows_without_tool_mention', no_tool)
print('\n--- tool mentions top40 ---')
for k, v in names.most_common(40):
    flag = '' if k in NAMES else '  <<< UNKNOWN'
    print('%6d  %s%s' % (v, k, flag))
print('\n--- UNKNOWN tool names (%d distinct) ---' % len(unknown))
for k, v in unknown.most_common(60):
    print('%6d  %s' % (v, k))
print('\n--- action/= forms top50 ---')
for k, v in acts.most_common(50):
    print('%6d  %s' % (v, k))
print('\n--- context samples (30) ---')
for k, v in ctx.most_common(30):
    print('%5d | %s' % (v, k))
