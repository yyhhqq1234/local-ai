# -*- coding: utf-8 -*-
"""分析 final-nsfw.jsonl 分布 + 检查被跳过窗口的来源文件"""
import json, os, collections

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
NSFW = os.path.join(BASE, "train", "data", "final-nsfw.jsonl")

c = collections.Counter()
lens, plens = [], []
topic_cnt = collections.Counter()
level_cnt = collections.Counter()
echo_cnt = 0
cont_cnt = 0
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
        if m.get("stype") == "cont":
            cont_cnt += 1
            u = r["messages"][0]["content"]
            a = r["messages"][-1]["content"]
            tail = u[-100:]
            if tail and tail in a[:300]:
                echo_cnt += 1

print("== final-nsfw.jsonl ==")
print("total:", sum(c.values()))
print("types:", dict(c))
print("avg_resp_len:", sum(lens)//max(len(lens),1), "min/max:", min(lens), max(lens))
print("avg_prompt_len:", sum(plens)//max(len(plens),1), "min/max:", min(plens), max(plens))
print("levels:", dict(level_cnt))
print("top topics:", topic_cnt.most_common(12))
print(f"cont={cont_cnt} echo={echo_cnt} ratio={echo_cnt/max(cont_cnt,1):.3f}")

# 读 coverage 报告看哪些文件覆盖率极低
cov_path = os.path.join(BASE, "train", "data", "nsfw-coverage.json")
if os.path.isfile(cov_path):
    cov = json.load(open(cov_path, encoding="utf-8"))
    low = [x for x in cov["per_file"] if x.get("coverage", 1) < 0.25]
    print(f"\n== 低覆盖率文件 (<25%) {len(low)} ==")
    for x in low:
        print(f"  {x['rel']}  cov={x['coverage']:.2%}  skip={x['skipped_windows']}/{x['windows_total']}")
