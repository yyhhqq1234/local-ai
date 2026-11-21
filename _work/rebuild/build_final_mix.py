# -*- coding: utf-8 -*-
"""最终训练集混配（清洗后）+ token 预算估算

输入（全部为清洗后产物，原始文件不动）：
  kitty  train/lines/9b-oxcoder/data/kitty-reverse/cleaned/kitty-clean-v3-phrasing-variants.jsonl
  nsfw   train/lines/9b-oxcoder/data/nsfw-gated/cleaned/nsfw-clean.jsonl
  dsh    train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v2.jsonl
         train/lines/9b-oxcoder/data/nsfw-gated/cleaned/dsh-clean.jsonl
输出：train/lines/9b-oxcoder/data/b1-combined/train-b1-v2.jsonl + mix-stats.json
配比目标（按行）：kitty 6000 / nsfw 7000（permit 全量 + regular 抽样）/ dsh 1500
"""
import io, json, os, random, sys

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
L9 = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder')
SUFFIX = (sys.argv[1] if len(sys.argv) > 1 else '')
OUT = os.path.join(L9, 'data', 'b1-combined', 'train-b1-v2%s.jsonl' % SUFFIX)
SMALL = SUFFIX == '-s'
STATS = os.path.join(L9, 'data', 'b1-combined', 'mix-stats.json')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def read(p, limit=None):
    out = []
    if not os.path.exists(p):
        print('  [miss]', os.path.basename(p))
        return out
    with io.open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if not (o.get('messages') or []):
                continue
            out.append(o)
            if limit and len(out) >= limit:
                break
    return out

def text_of(o):
    return sum(len(m.get('content') if isinstance(m.get('content'), str) else '') for m in o['messages'])

random.seed(20261121)
print('[1/4] kitty（清洗后，措辞变体档）')
kitty_all = read(os.path.join(L9, 'data/kitty-reverse/cleaned/kitty-clean-v3-phrasing-variants.jsonl'))
KITTY_N = 2200 if SMALL else 6000
kitty = random.sample(kitty_all, min(KITTY_N, len(kitty_all)))
print(f'  可用 {len(kitty_all)} → 取 {len(kitty)}')

print('[2/4] NSFW（清洗后）')
nsfw_all = read(os.path.join(L9, 'data/nsfw-gated/cleaned/nsfw-clean.jsonl'))
permit, regular = [], []
for o in nsfw_all:
    s = next((m.get('content') for m in o['messages'] if m.get('role') == 'system'), '') or ''
    (permit if '许可' in s else regular).append(o)
print(f'  许可 {len(permit)} / 常规 {len(regular)}')
REG_N = 600 if SMALL else 2000
PERMIT_N = 2200 if SMALL else len(permit)
nsfw = random.sample(permit, min(PERMIT_N, len(permit))) + random.sample(regular, min(REG_N, len(regular)))
print(f'  取 {len(nsfw)}（许可 {min(PERMIT_N, len(permit))} + 常规 {min(REG_N, len(regular))}）')

print('[3/4] DSH 适配')
dsh_a = read(os.path.join(L9, 'data/dsh-adapt/train-dsh-v3.jsonl'))      # 重建版：唯一答案率 93%
dsh_b = read(os.path.join(L9, 'data/nsfw-gated/cleaned/dsh-clean.jsonl')) # 清洗后真实样本
dsh_base = dsh_a + dsh_b
print('  DSH 适用答案唯一数: %d / %d' % (len({o['messages'][2]['content'] for o in dsh_base}), len(dsh_base)))
# 问法增广 ×4（答案不变，但保留唯一答案统计）
pre = ['帮我看下：', '直接做：']
dsh = list(dsh_base)
DSH_LIMIT = 900 if SMALL else 10**9
for o in dsh_base:
    q = o['messages'][1]['content']
    if len(q) > 80:
        continue
    for p in pre:
        rr = json.loads(json.dumps(o, ensure_ascii=False))
        rr['messages'][1]['content'] = p + q
        dsh.append(rr)
print(f'  base {len(dsh_base)}（唯一答案 {len({o["messages"][2]["content"] for o in dsh_base})}）→ 增广后 {len(dsh)}')

data = kitty + nsfw + dsh
random.shuffle(data)
chars = sum(text_of(o) for o in data)
# 中文约 1 token ≈ 1.35 字符（含标点），据此估 token
est_tok = chars / 1.35
with io.open(OUT, 'w', encoding='utf-8') as fh:
    for o in data:
        fh.write(json.dumps(o, ensure_ascii=False) + '\n')

cjk = sum(1 for o in data for ch in json.dumps(o, ensure_ascii=False) if '\u4e00' <= ch <= '\u9fff')
stats = {'rows': len(data), 'kitty': len(kitty), 'nsfw': len(nsfw), 'permit': len(nsfw) - min(2000, len(regular)),
         'regular': min(2000, len(regular)), 'dsh': len(dsh), 'dsh_unique_answers': len({o['messages'][2]['content'] for o in dsh_base}),
         'chars': chars, 'est_tokens': int(est_tok), 'cjk_chars': cjk}
json.dump(stats, io.open(STATS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('[4/4] 写出', OUT)
print(json.dumps(stats, ensure_ascii=False))
print(f'预计 1 epoch：{est_tok/1000:.0f}K token；按实测 190 tok/s ≈ {est_tok/190/3600:.1f} 小时')


