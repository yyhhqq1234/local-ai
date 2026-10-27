# -*- coding: utf-8 -*-
"""分析 final-nsfw.jsonl 分布 + v6 评测记录，输出优化依据"""
import json, os, sys, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
NSFW = os.path.join(BASE, "train", "data", "final-nsfw.jsonl")

c = collections.Counter()
lens, plens = [], []
topic_cnt = collections.Counter()
level_cnt = collections.Counter()
with open(NSFW, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        m = r.get("meta", {})
        c[m.get("stype", "?")] += 1
        lens.append(len(r["messages"][-1]["content"]))
        plens.append(len(r["messages"][0]["content"]))
        for t in m.get("topic", []):
            topic_cnt[t] += 1
        level_cnt[m.get("level", "?")] += 1

print("== final-nsfw.jsonl ==")
print("total:", sum(c.values()))
print("types:", dict(c))
print("avg_resp_len:", sum(lens) // max(len(lens), 1), "min/max:", min(lens), max(lens))
print("avg_prompt_len:", sum(plens) // max(len(plens), 1), "min/max:", min(plens), max(plens))
print("levels:", dict(level_cnt))
print("top topics:", topic_cnt.most_common(12))

# 检查续写类 prompt 的 lead 是否等于响应前缀（泄漏/回声风险）
echo = 0
tot = 0
with open(NSFW, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        m = r.get("meta", {})
        if m.get("stype") == "cont":
            tot += 1
            u = r["messages"][0]["content"]
            a = r["messages"][-1]["content"]
            # 若 user 尾部 100 字出现在 assistant 开头 200 字内 → 模型只需复读
            tail = u[-100:]
            if tail and tail in a[:300]:
                echo += 1
print("cont samples:", tot, "echo(lead在resp头部):", echo, "ratio=%.3f" % (echo / max(tot, 1)))

# 看 v6 训练数据里 nsfw 占比
for p in ("train/data/final-joint.jsonl",):
    fp = os.path.join(BASE, p)
    n = 0
    with open(fp, encoding="utf-8") as f:
        for line in f:
            n += 1
            if n > 20000:
                break
    print(p, "lines>=", n)
