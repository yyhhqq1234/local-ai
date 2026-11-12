# -*- coding: utf-8 -*-
"""深度审查补充统计：每类唯一答案 / 残留分类 / 正文伪 tool_call / 语言错配"""
import collections
import hashlib
import json
import re

P = "train/lines/27b-kittyrev/data/versions/gen3_1p4-nsfw-kitty.jsonl"

PATS = ["<tool_call>", "</tool_call>", "TODO", "FIXME", "占位", "待补", "XXX",
        "{{", "}}", "C:\\Users", "C:/Users", "autodl", "BaiduNetdisk", "/root/miniconda3",
        "miniconda3", "autodl-tmp"]

ans = collections.defaultdict(collections.Counter)
res = collections.Counter()
res_ex = collections.defaultdict(list)
tc_text = 0
tc_ex = []
ascii_rows = collections.defaultdict(list)
multi_asst = 0

for line in open(P, encoding="utf-8"):
    d = json.loads(line)
    m = d["messages"]
    cat = (d.get("meta") or {}).get("cat")
    assts = [x for x in m if x.get("role") == "assistant"]
    if len(assts) > 1:
        multi_asst += 1
    a = "".join(x.get("content") or "" for x in assts).strip()
    if a:
        ans[cat][hashlib.blake2b(a.encode(), digest_size=8).hexdigest()] += 1
    blob = "".join((x.get("content") or "") for x in m)
    for pat in PATS:
        if pat in blob:
            res[pat] += 1
            if len(res_ex[pat]) < 3:
                res_ex[pat].append((cat, a[:70]))
    if "<tool_call>" in blob:
        tc_text += 1
        if len(tc_ex) < 5:
            tc_ex.append((cat, blob[:120].replace("\n", " ")))
    if a:
        r = sum(1 for c in a if ord(c) < 128) / max(1, len(a))
        if r > 0.8:
            ascii_rows[cat].append(a[:90])

print("== 每类唯一答案 / 行数 ==")
for c, cnt in sorted(ans.items(), key=lambda x: -sum(x[1].values())):
    tot = sum(cnt.values())
    print(f"  {str(c):16s} rows={tot:6d} uniq={len(cnt):5d} avg_clone={tot / max(1, len(cnt)):.1f}")

print("\n== 残留分类（行数） ==")
for k, v in res.most_common():
    print(f"  {k:16s} {v}")

print("\n== 残留示例 ==")
for k in ("TODO", "FIXME", "占位", "待补", "XXX", "{{", "C:\\Users", "miniconda3", "autodl-tmp"):
    if res_ex.get(k):
        print(f"  [{k}]")
        for cat, s in res_ex[k][:2]:
            print(f"     {cat}: {s}")

print(f"\n== 正文伪 <tool_call> 文本行 = {tc_text}")
for cat, s in tc_ex:
    print(f"   {cat}: {s}")

print(f"\n== 单行多个 assistant 的行数 = {multi_asst}")

print("\n== ascii 占比 >80% 按类 ==")
for c, v in sorted(ascii_rows.items(), key=lambda x: -len(x[1])):
    print(f"  {str(c):16s} {len(v):5d} | {v[0][:80]}")
