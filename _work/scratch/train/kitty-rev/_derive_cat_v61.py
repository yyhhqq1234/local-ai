# -*- coding: utf-8 -*-
"""给 v61-mix 补 meta.cat（check_sft 硬要求）
1189 条的 cat 从 train.final.cat.jsonl 的派生结果里按 id 取；
54 条 nonkitty 用 kb-re。"""
import json, hashlib
from collections import Counter

# 1) 读 V6 的派生结果（id -> cat）
id2cat = {}
catfile = "data/intent3/v6-mix/train.final.cat.jsonl"
for line in open(catfile, encoding="utf-8"):
    if not line.strip(): continue
    r = json.loads(line)
    rid = r.get("id")
    c = (r.get("meta") or {}).get("cat")
    if rid and c: id2cat[rid] = c
print(f"从 train.final.cat.jsonl 读到 {len(id2cat)} 个 id->cat")

# 2) 读 v61-mix.dictargs，补 cat，写出 v61-mix.cat.dictargs.jsonl
src = "data/intent3/v6-mix/v61-mix.dictargs.jsonl"
dst = "data/intent3/v6-mix/v61-mix.cat.dictargs.jsonl"
rows = []
miss = 0
for line in open(src, encoding="utf-8"):
    if not line.strip(): continue
    r = json.loads(line)
    rid = r.get("id")
    m = r.setdefault("meta", {})
    if m.get("src") == "v61-nonkitty":
        m["cat"] = "kb-re"
    elif rid in id2cat:
        m["cat"] = id2cat[rid]
    else:
        m["cat"] = "kb-re"   # 兜底
        miss += 1
    rows.append(r)

with open(dst, "w", encoding="utf-8") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")

print(f"写出 {len(rows)} 条 → {dst}")
print("md5", hashlib.md5(open(dst,'rb').read()).hexdigest())
print("未匹配 id 用兜底:", miss)
print("cat 分布:", dict(Counter((r['meta'] or {}).get('cat') for r in rows)))
print("kind 分布:", dict(Counter((r['meta'] or {}).get('kind') for r in rows)))
# 断言：零 None
none_cat = sum(1 for r in rows if not (r.get('meta') or {}).get('cat'))
print(f"meta.cat 为空的条数: {none_cat}")
assert none_cat == 0, "仍有空 cat"
print("✅ cat 补齐完成")
