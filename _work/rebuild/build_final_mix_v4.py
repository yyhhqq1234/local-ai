# -*- coding: utf-8 -*-
"""b1v4 混配：NSFW 三路（零起点 45 / 续写 40 / 前置 15）+ 工具近邻同义 + DSH + kitty

针对 v3 的两个实测问题：
  ① 零起点双峰随机（55%）→ 换 v4 数据（前 300 字 ≥3 露骨词占 100%，答案全不重复）
  ② 续写回退（1/3）→ 给回 40% 配额，v4 续写行开头本身 ≥2 露骨词
配合训练侧 ctx 1024（v3 用 768，截掉 34% token，nsfw 正文尾部信息被丢）

用法: python _work/rebuild/build_final_mix_v4.py
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
sys.path.insert(0, os.path.join(ROOT, 'train', 'lines', '_shared', 'scripts'))
import nsfw_gate_eval as M

random.seed(20261123)
STRICT = M.load_terms(strict=True)

ap = argparse.ArgumentParser()
ap.add_argument('--out', default='train-b1-v4.jsonl')
ap.add_argument('--ctx', type=int, default=1024)
a = ap.parse_args()

P = {
    'kitty': 'data/kitty-reverse/opt/kitty-downsampled.jsonl',
    'nb': 'data/kitty-reverse/opt/tool-neighbor.jsonl',
    'syn': 'data/kitty-reverse/opt/tool-synonym.jsonl',
    'dsh1': 'data/dsh-adapt/train-dsh-v3.jsonl',
    'dsh2': 'data/nsfw-gated/cleaned/dsh-clean.jsonl',
    'z4': 'data/nsfw-gated/cleaned/opt/nsfw-zeroshot-v4.jsonl',
    'c4': 'data/nsfw-gated/cleaned/opt/nsfw-continue-v4.jsonl',
    'f4': 'data/nsfw-gated/cleaned/opt/nsfw-frontload-v4.jsonl',
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


def take(rows, n):
    random.shuffle(rows)
    return rows[:n]


rows = []

kitty = take(read(P['kitty']), 1600)
rows += kitty
print('[1/5] kitty %d' % len(kitty))

tool = read(P['nb']) + read(P['syn'])
tool = tool * 2
rows += tool
print('[2/5] tool %d（×2）' % len(tool))

dsh = read(P['dsh1']) + read(P['dsh2'])
dsh = dsh * 2
rows += dsh
print('[3/5] dsh %d（×2）' % len(dsh))

# NSFW 三路 45 / 40 / 15（总量 3000）
N_NSFW = 3000
z = take(read(P['z4']), int(N_NSFW * 0.45))
c = take(read(P['c4']), int(N_NSFW * 0.40))
f = take(read(P['f4']), N_NSFW - len(z) - len(c))
nsfw = z + c + f
rows += nsfw
print('[4/5] nsfw %d（零起点 %d / 续写 %d / 前置 %d）' % (len(nsfw), len(z), len(c), len(f)))

random.shuffle(rows)
outp = os.path.join(OUT_DIR, a.out)
os.makedirs(OUT_DIR, exist_ok=True)
with io.open(outp, 'w', encoding='utf-8') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')

# 估算：按 ctx 计的有效 token（每样本 min(实际, ctx)）
def toks(r):
    c = sum(len(m['content']) for m in r['messages'])
    return min(int(c / 1.35), a.ctx)


tot = sum(toks(r) for r in rows)
chars = sum(sum(len(m['content']) for m in r['messages']) for r in rows)
trunc = sum(1 for r in rows if sum(len(m['content']) for m in r['messages']) / 1.35 > a.ctx)
steps = max(1, int(tot / a.ctx / 8))
print(json.dumps({'rows': len(rows), 'kitty': len(kitty), 'tool': len(tool), 'dsh': len(dsh),
                  'nsfw': len(nsfw), 'chars': chars, 'ctx': a.ctx,
                  'eff_tokens': tot, 'truncated_rows': trunc,
                  'est_steps': steps, 'est_hours_at_9.3s': round(steps * 9.3 / 3600, 2)}, ensure_ascii=False))
print('[out]', outp)
