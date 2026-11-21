# -*- coding: utf-8 -*-
"""b1v5 混配：v4 基础上加三件套（pchain / ida / 直接答问）

治三个实测病：
  ① 指针链→kitty_ce 误路由   → tool-pchain ×2
  ② 反编译缺 target          → tool-ida ×2
  ③ 短问句答非所问/空回复     → tool-direct-answer ×3
"""
import io
import json
import os
import random
import sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
L9 = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder')
OUT = os.path.join(L9, 'data', 'b1-combined', 'train-b1-v5.jsonl')
random.seed(20261124)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


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
kitty = take(read('data/kitty-reverse/opt/kitty-downsampled.jsonl'), 1500)
rows += kitty
tool = read('data/kitty-reverse/opt/tool-neighbor.jsonl') + read('data/kitty-reverse/opt/tool-synonym.jsonl')
rows += tool * 2
dsh = (read('data/dsh-adapt/train-dsh-v3.jsonl') + read('data/nsfw-gated/cleaned/dsh-clean.jsonl')) * 2
rows += dsh
pch = read('data/kitty-reverse/opt/tool-pchain.jsonl') * 2
ida = read('data/kitty-reverse/opt/tool-ida.jsonl') * 2
direct = read('data/dsh-adapt/tool-direct-answer.jsonl') * 3
rows += pch + ida + direct
z = take(read('data/nsfw-gated/cleaned/opt/nsfw-zeroshot-v4.jsonl'), 1350)
c = take(read('data/nsfw-gated/cleaned/opt/nsfw-continue-v4.jsonl'), 1200)
f = take(read('data/nsfw-gated/cleaned/opt/nsfw-frontload-v4.jsonl'), 400)
rows += z + c + f
random.shuffle(rows)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + '\n')

chars = sum(sum(len(m['content']) for m in r['messages']) for r in rows)
print(json.dumps({'rows': len(rows), 'kitty': len(kitty), 'tool': len(tool) * 2,
                  'dsh': len(dsh), 'pchain': len(pch), 'ida': len(ida), 'direct': len(direct),
                  'nsfw': len(z) + len(c) + len(f), 'chars': chars,
                  'est_tokens': int(chars / 1.35)}, ensure_ascii=False))
print('[out]', OUT)
