# -*- coding: utf-8 -*-
"""验证近似去重是否过合并：抽样 cluster 内成员，算真实 Jaccard + 工具签名是否相同。只读 cleaned 输入源。"""
import json, os, re, sys, io, collections, zlib
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(ROOT, 'train/lines/9b-oxcoder/data/kitty-reverse')
FILES = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
         'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']
MF = {m['name']: m for m in json.load(open(os.path.join(ROOT, '_work/rebuild/kitty-adapt/manifest.json'), encoding='utf-8'))}
PAIR = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)\s*[`\'"]?\s*(action|op)\s*[=:]\s*[`\'"]?([^\s`\'"，。；、）)】\n]+)')

def norm(s):
    return ' '.join((s or '').lower().split())

def sh(t):
    t = norm(t)
    if len(t) < 5:
        return np.array([], dtype=np.int64)
    return np.fromiter((zlib.crc32(t[i:i+5].encode()) for i in range(len(t)-4)), dtype=np.int64, count=len(t)-4)

def jac(a, b):
    ua, ub = np.unique(a), np.unique(b)
    if ua.size == 0 or ub.size == 0:
        return 0.0
    inter = np.intersect1d(ua, ub, assume_unique=True).size
    return inter / (ua.size + ub.size - inter)

rows = {}
for f in FILES:
    for i, line in enumerate(open(os.path.join(SRC, f), encoding='utf-8')):
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        a = '\n'.join(m.get('content') or '' for m in o['messages'] if m.get('role') == 'assistant')
        u = '\n'.join(m.get('content') or '' for m in o['messages'] if m.get('role') == 'user')
        rows[(f, i)] = (u, a)

def sig(t):
    return tuple(sorted('%s %s=%s' % (m.group(1), m.group(2), m.group(3)) for m in PAIR.finditer(t)))

# 从隔离区/保留区取样本对
s = json.load(open(os.path.join(ROOT, '_work/clean/kitty/stats.json'), encoding='utf-8'))
ex = [e for e in s['dedup']['examples'] if e['pass'] == 'near']
for e in ex[:6]:
    k = (e['kept_src'], e['kept_idx']); d = (e['dropped_src'], e['dropped_idx'])
    if k not in rows or d not in rows:
        print('skip', k, d); continue
    u1, a1 = rows[k]; u2, a2 = rows[d]
    j = jac(sh(u1 + '\n' + a1), sh(u2 + '\n' + a2))
    s1, s2 = sig(a1), sig(a2)
    print('=' * 70)
    print('jaccard=%.3f  same_sig=%s  cluster=%s' % (j, s1 == s2, e.get('cluster')))
    print('KEPT   user:', u1[:70].replace('\n', ' '))
    print('KEPT   asst:', a1[:150].replace('\n', ' '))
    print('DROP   user:', u2[:70].replace('\n', ' '))
    print('DROP   asst:', a2[:150].replace('\n', ' '))
    print('sig1', s1[:3], '\nsig2', s2[:3])
