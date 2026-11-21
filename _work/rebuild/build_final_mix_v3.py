# -*- coding: utf-8 -*-
"""b1 混配 v3：加入工具近邻/同义集与零起点 NSFW 集

构成（默认小档，约 7-8k 行）：
  kitty   : kitty-downsampled.jsonl（kitty_ce 降到 15% 上限）          1800
  tool    : tool-neighbor.jsonl + tool-synonym.jsonl（唯一答案 100%）   487（×2 = 974）
  dsh     : train-dsh-v3.jsonl + dsh-clean.jsonl                       440（×2 = 880）
  nsfw    : nsfw-zeroshot.jsonl（零起点）+ nsfw-clean-v2.jsonl         2800（零起点 ≥800）
用法: python _work/rebuild/build_final_mix_v3.py -s
"""
import argparse
import io
import json
import os
import random
import sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
L9 = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder')
OUT_DIR = os.path.join(L9, 'data', 'b1-combined')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
random.seed(20261122)

sys.path.insert(0, os.path.join(ROOT, 'train', 'lines', '_shared', 'scripts'))
import nsfw_gate_eval as M
STRICT = M.load_terms(strict=True)


def n_explicit(o):
    a = next((m['content'] for m in o['messages'] if m.get('role') == 'assistant'), '') or ''
    return sum(a.count(t) for t in STRICT)

ap = argparse.ArgumentParser()
ap.add_argument('-s', action='store_true', help='小档（默认大档）')
ap.add_argument('--out', default='train-b1-v3-s.jsonl')
a = ap.parse_args()

P = {
    'kitty_ds': 'data/kitty-reverse/opt/kitty-downsampled.jsonl',
    'tool_nb': 'data/kitty-reverse/opt/tool-neighbor.jsonl',
    'tool_syn': 'data/kitty-reverse/opt/tool-synonym.jsonl',
    'dsh_v3': 'data/dsh-adapt/train-dsh-v3.jsonl',
    'dsh_clean': 'data/nsfw-gated/cleaned/dsh-clean.jsonl',
    'nsfw_zero': 'data/nsfw-gated/cleaned/opt/nsfw-zeroshot.jsonl',
    'nsfw_v2': 'data/nsfw-gated/cleaned/opt/nsfw-clean-v2.jsonl',
    'nsfw_old': 'data/nsfw-gated/cleaned/nsfw-clean.jsonl',
}


def read(rel):
    p = os.path.join(L9, rel.replace('/', os.sep))
    if not os.path.exists(p):
        print('  [miss]', rel)
        return []
    out = []
    for line in io.open(p, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get('messages'):
            out.append(o)
    return out


def is_permit(o):
    s = next((m['content'] for m in o['messages'] if m.get('role') == 'system'), '') or ''
    return '许可' in s


def aug(rows, pres, limit=None):
    out = []
    for r in rows:
        for p in pres:
            m = [dict(x) for x in r['messages']]
            u = next((x for x in m if x['role'] == 'user'), None)
            if u is None:
                continue
            u['content'] = p + u['content']
            out.append({'messages': m})
    if limit:
        random.shuffle(out)
        out = out[:limit]
    return out


def mix(name, copies):
    out = []
    for _ in range(copies):
        out.extend([{'messages': [dict(x) for x in r['messages']]} for r in name])
    return out


rows = []

# 1 kitty（下采样后）
kitty = read(P['kitty_ds']) or read('data/kitty-reverse/cleaned/kitty-clean-v3.jsonl')
n_kitty = 1800 if a.s else 5000
random.shuffle(kitty)
kitty = kitty[:n_kitty]
rows += kitty
print('[1/4] kitty %d' % len(kitty))

# 2 工具（近邻 + 同义，×2 提升权重）
nb, syn = read(P['tool_nb']), read(P['tool_syn'])
tool = mix(nb + syn, 2)
rows += tool
print('[2/4] tool %d（neighbor %d + synonym %d，×2）' % (len(tool), len(nb), len(syn)))

# 3 DSH
dsh = read(P['dsh_v3']) + read(P['dsh_clean'])
dsh = aug(dsh, ['直接做：', '帮我看下：'])  # 只做问法增广，不复制答案语义
rows += dsh
print('[3/4] dsh %d（基础 %d ×2 问法）' % (len(dsh), len(dsh) // 2))

# 4 NSFW：零起点优先
zero = [o for o in read(P['nsfw_zero']) if n_explicit(o) >= 5]
v2 = read(P['nsfw_v2']) or read(P['nsfw_old'])
v2 = [o for o in v2 if is_permit(o) and n_explicit(o) >= 5]
n_total = 2800 if a.s else 7000
n_zero = min(len(zero), 1000 if a.s else 2400)
zero_s = zero[:n_zero]
random.shuffle(v2)
rest = v2[:max(0, n_total - len(zero_s))]
nsfw = zero_s + rest
rows += nsfw
print('[4/4] nsfw %d（零起点 %d + 常规 permit %d）' % (len(nsfw), len(zero_s), len(rest)))

random.shuffle(rows)
os.makedirs(OUT_DIR, exist_ok=True)
outp = os.path.join(OUT_DIR, a.out)
with io.open(outp, 'w', encoding='utf-8') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')

chars = sum(sum(len(m['content']) for m in r['messages']) for r in rows)
cjk = sum(1 for r in rows for m in r['messages'] for ch in m['content'] if '\u4e00' <= ch <= '\u9fff')
print(json.dumps({'rows': len(rows), 'kitty': len(kitty), 'tool': len(tool), 'dsh': len(dsh),
                  'nsfw': len(nsfw), 'nsfw_zero': len(zero_s), 'chars': chars,
                  'est_tokens': int(chars / 1.35), 'cjk': cjk}, ensure_ascii=False))
print('预计 1 epoch：%dK token；按 190 tok/s ≈ %.1f 小时' % (chars / 1350, chars / 1.35 / 190 / 3600))
print('[out]', outp)

