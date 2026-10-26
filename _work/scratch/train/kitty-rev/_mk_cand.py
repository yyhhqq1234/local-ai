# -*- coding: utf-8 -*-
"""从 v5-mix 均匀采样 60 条 user prompt，构造 answer 侧候选池（用于筛 base 会拒的题）"""
import json, os
src = "data/intent3/v5-mix/train.jsonl"
rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
users = []
for r in rows:
    for m in r.get("messages", []):
        if m.get("role") == "user":
            c = (m.get("content") or "").strip()
            if 8 <= len(c) <= 300:      # 太短没判别力，太长跑得慢
                users.append(c)
            break
print("pool size:", len(users))
N = 60
step = max(1, len(users) // N)
picked = [users[i] for i in range(0, len(users), step)][:N]
# 去重
seen, out = set(), []
for c in picked:
    if c in seen: continue
    seen.add(c)
    out.append({"id": f"cd-{len(out)+1:03d}", "prompt": c,
                "expected": "answer", "cat": "kitty", "why": "kitty 逆向技术问答，应当作答"})
os.makedirs("data/intent3", exist_ok=True)
with open("data/intent3/cand-60.jsonl", "w", encoding="utf-8") as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")
print("written:", len(out), "-> data/intent3/cand-60.jsonl")
for o in out[:5]:
    print(" ", o["id"], o["prompt"][:60])
