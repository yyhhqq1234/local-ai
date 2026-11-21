# -*- coding: utf-8 -*-
"""对 cleaned 产物做独立复验（不复用清洗器逻辑）：格式/工具/action/泄漏/控制字符/长度/残留近重复/覆盖率。"""
import json, os, re, sys, io, collections, zlib
import numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CLEAN = os.path.join(ROOT, 'train/lines/9b-oxcoder/data/kitty-reverse/cleaned')
EVAL_DIR = os.path.join(ROOT, 'train/lines/9b-oxcoder/data/eval')
MF = {m['name']: m for m in json.load(open(os.path.join(ROOT, '_work/rebuild/kitty-adapt/manifest.json'), encoding='utf-8'))}
NAMES = set(MF)
TOOL_TOKEN = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)')
PAIR = re.compile(r'(?<![A-Za-z0-9_])((?:kitty|reverse)_[a-z0-9_]+)\s*[`\'"]?\s*(action|op)\s*[=:]\s*[`\'"]?([A-Za-z0-9_\-|./:<>\[\]=]+)')
CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def norm(s):
    return ' '.join((s or '').lower().split())

def sh(t):
    t = norm(t)
    if len(t) < 5:
        return np.array([], dtype=np.int64)
    return np.fromiter((zlib.crc32(t[i:i + 5].encode()) for i in range(len(t) - 4)), dtype=np.int64, count=len(t) - 4)

def jac(a, b):
    ua, ub = np.unique(a), np.unique(b)
    if ua.size == 0 or ub.size == 0:
        return 0.0
    inter = np.intersect1d(ua, ub, assume_unique=True).size
    return inter / (ua.size + ub.size - inter)

eval_users = set()
for split in ('val', 'test'):
    d = os.path.join(EVAL_DIR, split)
    for fn in os.listdir(d):
        if not fn.endswith('.jsonl'):
            continue
        for line in open(os.path.join(d, fn), encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            for m in (o.get('messages') or []):
                if m.get('role') == 'user':
                    eval_users.add(norm(m.get('content') or '')[:200])
print('eval user fingerprints:', len(eval_users))

TARGETS = ['kitty-clean-v3.jsonl', 'kitty-clean-v3-phrasing-variants.jsonl',
           'clean-train-kitty-v3-clean.jsonl', 'clean-kitty-v6-fix.jsonl',
           'clean-kitty-v7-direct-answer.jsonl', 'clean-kitty-v5-strong.jsonl',
           'clean-kitty-adapt-v2.jsonl']

summary = {}
for fn in TARGETS:
    p = os.path.join(CLEAN, fn)
    n = bad_json = bad_role = empty_asst = ctrl_rows = 0
    unknown = collections.Counter()
    bad_act = collections.Counter()
    leak = 0
    over = 0
    lens = []
    pairs = set()
    tools = collections.Counter()
    users = []
    texts = []
    for line in open(p, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
        except Exception:
            bad_json += 1
            continue
        msgs = o.get('messages') or []
        roles = [m.get('role') for m in msgs]
        if not roles or roles[-1] != 'assistant' or any(r not in ('system', 'user', 'assistant') for r in roles):
            bad_role += 1
            continue
        asst = '\n'.join(m.get('content') or '' for m in msgs if m['role'] == 'assistant')
        user = '\n'.join(m.get('content') or '' for m in msgs if m['role'] == 'user')
        if not asst.strip():
            empty_asst += 1
        if CTRL.search(asst) or CTRL.search(user):
            ctrl_rows += 1
        tot = sum(len(m.get('content') or '') for m in msgs)
        lens.append(tot)
        if tot > 4000:
            over += 1
        if norm(user)[:200] in eval_users:
            leak += 1
        for t in TOOL_TOKEN.findall(asst):
            if t not in NAMES and not t.endswith('_'):
                unknown[t] += 1
        for m in PAIR.finditer(asst):
            t, kind, raw = m.group(1), m.group(2), m.group(3)
            if t not in NAMES or raw.startswith('<') or '<' in raw:
                continue
            parts = [x for x in raw.split('/') if x]
            ok = all((x in (MF[t].get('actions') or [])) if kind == 'action'
                     else (('*' in (MF[t].get('ops') or [])) or x.split('|')[0] in (MF[t].get('ops') or []))
                     for x in parts)
            if ok:
                pairs.add('%s %s=%s' % (t, kind, parts[0]))
            else:
                bad_act[(t, kind, raw)] += 1
            tools[t] += 1
        users.append(user)
        texts.append(asst)
    lens.sort()

    # 残留近重复抽样：按 user+assistant 合并文本算 Jaccard（前 1200 条，窗口 40），>0.9 算残留
    resid = 0
    comb = [sh(users[i] + '\n' + texts[i]) for i in range(min(1200, len(users)))]
    for i in range(len(comb)):
        for k in range(i + 1, min(len(comb), i + 40)):
            if jac(comb[i], comb[k]) >= 0.9:
                resid += 1
    summary[fn] = dict(rows=n, bad_json=bad_json, bad_role=bad_role, empty_asst=empty_asst,
                       ctrl=ctrl_rows, leak=leak, over4000=over,
                       unknown_tool=dict(unknown), bad_action=len(bad_act),
                       distinct_pairs=len(pairs), distinct_tools=len(tools),
                       p50=lens[len(lens) // 2] if lens else 0, max=lens[-1] if lens else 0,
                       near_dup_residual_pairs_sample=resid)
    print('\n== %s' % fn)
    print(' rows=%d bad_json=%d bad_role=%d empty_asst=%d ctrl=%d leak=%d >4000=%d unknown=%s bad_action=%d'
          % (n, bad_json, bad_role, empty_asst, ctrl_rows, leak, over, dict(unknown), len(bad_act)))
    print(' distinct tool-action pairs=%d distinct tools=%d p50len=%d maxlen=%d residual_near_dup(sample)=%d'
          % (len(pairs), len(tools), summary[fn]['p50'], summary[fn]['max'], resid))
    if bad_act:
        print(' bad_action patterns:', bad_act.most_common(5))

out = os.path.join(ROOT, '_work/clean/kitty/verify_result.json')
json.dump(summary, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\nwritten', out)

# ---- 覆盖率对照：原始输入 vs 合并产物
SRC = os.path.join(ROOT, 'train/lines/9b-oxcoder/data/kitty-reverse')
INPUTS = ['train-kitty-v3-clean.jsonl', 'kitty-v6-fix.jsonl', 'kitty-v7-direct-answer.jsonl',
          'kitty-v5-strong.jsonl', 'kitty-adapt-v2.jsonl']

def coverage(paths):
    tools, pairs = collections.Counter(), set()
    for p in paths:
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            asst = '\n'.join(m.get('content') or '' for m in o['messages'] if m.get('role') == 'assistant')
            for t in TOOL_TOKEN.findall(asst):
                if t in NAMES:
                    tools[t] += 1
            for m in PAIR.finditer(asst):
                if m.group(1) in NAMES and not m.group(3).startswith('<'):
                    pairs.add('%s %s=%s' % (m.group(1), m.group(2), m.group(3).split('/')[0]))
    return tools, pairs

tin, pin = coverage([os.path.join(SRC, f) for f in INPUTS])
tout, pout = coverage([os.path.join(CLEAN, 'kitty-clean-v3.jsonl')])
print('\n=== 覆盖率对照（原始 -> 合并产物） ===')
print('tools: %d -> %d ; 消失的工具: %s' % (len(tin), len(tout), sorted(set(tin) - set(tout)) or '无'))
print('工具-动作对: %d -> %d ; 消失 %d 个' % (len(pin), len(pout), len(pin - pout)))
miss = sorted(pin - pout)
print('消失样例(前20):', miss[:20])
print('净增(改写产生):', sorted(pout - pin)[:10])
cov = {'tools_in': len(tin), 'tools_out': len(tout),
       'missing_tools': sorted(set(tin) - set(tout)),
       'pairs_in': len(pin), 'pairs_out': len(pout),
       'missing_pairs': miss, 'missing_pairs_count': len(miss),
       'added_pairs': sorted(pout - pin),
       'tool_counts_in': dict(tin), 'tool_counts_out': dict(tout)}
json.dump(cov, open(os.path.join(ROOT, '_work/clean/kitty/coverage.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

