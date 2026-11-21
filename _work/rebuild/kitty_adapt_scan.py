# -*- coding: utf-8 -*-
"""kitty 工具面适配：从更新后的 kitty-toolbox（只读）抽取工具/action 面，与现有训练数据对比覆盖"""
import io, json, os, re, sys

KITTY = r'D:\DrCE(26.2.16)\kitty-toolbox'
ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
OUT_DIR = ROOT + r'\_work\rebuild\kitty-adapt'
os.makedirs(OUT_DIR, exist_ok=True)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

man = io.open(os.path.join(KITTY, 'src', 'tool-manifest.ts'), encoding='utf-8', errors='replace').read()
# 解析 { name: 'kitty_x', channel: '...', actions: [...], ops?: [...], description: '...' }
entries = []
for m in re.finditer(r"\{\s*name:\s*'([^']+)',\s*channel:\s*'([^']*)',\s*actions:\s*\[([^\]]*)\](.*?)\}", man, re.S):
    name, ch, acts, rest = m.group(1), m.group(2), m.group(3), m.group(4)
    acts = [a.strip().strip("'\"") for a in acts.split(',') if a.strip()]
    ops_m = re.search(r"ops:\s*\[([^\]]*)\]", rest)
    ops = [o.strip().strip("'\"") for o in ops_m.group(1).split(',')] if ops_m else []
    desc_m = re.search(r"description:\s*'([^']*)'", rest)
    entries.append({'name': name, 'channel': ch, 'actions': acts, 'ops': ops,
                    'description': desc_m.group(1) if desc_m else ''})

json.dump(entries, io.open(os.path.join(OUT_DIR, 'manifest.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('工具数:', len(entries))
for e in entries:
    print(f"  {e['name']:20s} ch={e['channel']:14s} actions={len(e['actions']):2d} {e['actions'][:6]}")

# 现有训练数据里出现的 kitty_* 工具与 action
data_files = [
    ROOT + r'\train\lines\9b-oxcoder\data\kitty-reverse\train-kitty-v3-clean.jsonl',
    ROOT + r'\train\lines\9b-oxcoder\data\kitty-reverse\kitty-v6-fix.jsonl',
    ROOT + r'\train\lines\9b-oxcoder\data\kitty-reverse\kitty-v7-direct-answer.jsonl',
    ROOT + r'\train\lines\9b-oxcoder\data\kitty-reverse\kitty-v5-strong.jsonl',
]
seen_tools, seen_actions = {}, {}
for p in data_files:
    if not os.path.exists(p):
        continue
    with io.open(p, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            txt = json.dumps(o, ensure_ascii=False)
            for t in re.findall(r'\bkitty_[a-z0-9_]+', txt):
                seen_tools[t] = seen_tools.get(t, 0) + 1
            for a in re.findall(r'\baction=([a-zA-Z0-9_-]+)', txt):
                seen_actions[a] = seen_actions.get(a, 0) + 1

man_names = {e['name'] for e in entries}
print('\n现有数据覆盖:', len(seen_tools), '个 kitty_*')
miss = sorted(man_names - set(seen_tools))
print('清单有、数据无的工具:', miss if miss else '无')
extra = sorted(set(seen_tools) - man_names)
print('数据有、清单无（过期工具）:', extra[:12] if extra else '无')
json.dump({'seen_tools': seen_tools, 'seen_actions': seen_actions, 'missing': miss, 'stale': extra},
          io.open(os.path.join(OUT_DIR, 'coverage.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\n样例 action 统计前 20:', sorted(seen_actions.items(), key=lambda kv: -kv[1])[:20])
