# -*- coding: utf-8 -*-
"""粗略画像：5 个来源的 records 结构、role 序列、工具/action 出现形态。只读。"""
import json, re, sys, collections, os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(BASE, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']

for f in FILES:
    p = os.path.join(SRC, f)
    n = 0; roles = collections.Counter(); keys = collections.Counter()
    bad = 0; toolmiss = []; actmiss = []
    lens = []
    sysdump = set()
    for line in open(p, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
        except Exception:
            bad += 1
            continue
        keys.update(o.keys())
        msgs = o.get('messages')
        if not isinstance(msgs, list):
            bad += 1
            continue
        seq = tuple(m.get('role') for m in msgs if isinstance(m, dict))
        roles[seq] += 1
        total = sum(len(m.get('content') or '') for m in msgs if isinstance(m, dict))
        lens.append(total)
        for m in msgs:
            if m.get('role') == 'system':
                sysdump.add((m.get('content') or '')[:60])
    lens.sort()
    print('=' * 70)
    print(f, 'rows', n, 'bad_json', bad)
    print(' top-level keys', dict(keys))
    print(' role seqs', roles.most_common(6))
    if lens:
        print(' total chars: min %d p50 %d p90 %d max %d' % (lens[0], lens[len(lens)//2], lens[int(len(lens)*.9)], lens[-1]))
    print(' system variants', len(sysdump))
    for s in list(sysdump)[:3]:
        print('   sys:', s.replace('\n', ' / '))
