# -*- coding: utf-8 -*-
"""构建 imatrix 校准文本：只用自有清洗语料（kitty / NSFW permit / DSH），取 assistant 正文拼接

输出 _work/quant/calib-b1.txt（每行一条，约 300–500 KB）
"""
import io, json, os, random, sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
L9 = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder')
OUT = os.path.join(ROOT, '_work', 'quant', 'calib-b1.txt')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
random.seed(20261121)

def take(path, n, filt=None):
    rows = []
    if not os.path.exists(path):
        print('  [miss]', os.path.basename(path))
        return rows
    with io.open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            msgs = o.get('messages') or []
            u = next((m.get('content') for m in msgs if m.get('role') == 'user'), '')
            a = next((m.get('content') for m in msgs if m.get('role') == 'assistant'), '')
            if isinstance(u, list):
                u = ''.join(x.get('text', '') for x in u)
            if isinstance(a, list):
                a = ''.join(x.get('text', '') for x in a)
            if not a:
                continue
            if filt and not filt(a, u):
                continue
            rows.append((u, a))
    random.shuffle(rows)
    return rows[:n]

def permit(a, u):
    return True

lines = []
print('[1/3] kitty')
for u, a in take(os.path.join(L9, 'data/kitty-reverse/cleaned/kitty-clean-v3.jsonl'), 220):
    lines.append((u + '\n' + a) if u else a)
print('[2/3] nsfw permit')
c = 0
p = os.path.join(L9, 'data/nsfw-gated/cleaned/nsfw-clean.jsonl')
if os.path.exists(p):
    with io.open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if c >= 160:
                break
            try:
                o = json.loads(line)
            except Exception:
                continue
            msgs = o.get('messages') or []
            s = next((m.get('content') for m in msgs if m.get('role') == 'system'), '') or ''
            if '许可' not in s:
                continue
            a = next((m.get('content') for m in msgs if m.get('role') == 'assistant'), '')
            if isinstance(a, list):
                a = ''.join(x.get('text', '') for x in a)
            if a:
                lines.append(a)
                c += 1
print('  取', c)
print('[3/3] dsh')
for u, a in take(os.path.join(L9, 'data/dsh-adapt/train-dsh-v3.jsonl'), 80):
    lines.append(u + '\n' + a)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as fh:
    for t in lines:
        fh.write(t.replace('\r', ' ').replace('\n', ' ') + '\n')
size = os.path.getsize(OUT)
print(f'[out] {OUT} 条数={len(lines)} 大小={size/1024:.0f} KB 平均={size/max(1,len(lines)):.0f} B')
