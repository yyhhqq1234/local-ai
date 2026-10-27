# -*- coding: utf-8 -*-
"""验证 v3 输出：抽样检查 + 低覆盖率文件确认 + 回声检测"""
import json, os, sys

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
V3 = os.path.join(BASE, "train", "data", "nsfw-v3.jsonl")
COV = os.path.join(BASE, "train", "data", "nsfw-v3-coverage.json")

# 1) 总条数 + 类型分布
n = 0
types = {}
minor_n = 0
echo_n = 0
cont_n = 0
resp_lens = []
with open(V3, encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        n += 1
        m = r["meta"]
        t = m["stype"]
        types[t] = types.get(t, 0) + 1
        if m.get("minor_flag"):
            minor_n += 1
        a = r["messages"][-1]["content"]
        resp_lens.append(len(a))
        if t == "cont":
            cont_n += 1
            u = r["messages"][0]["content"]
            tail = u[-100:]
            if tail and tail in a[:300]:
                echo_n += 1

print(f"total={n}")
print(f"types={types}")
print(f"minor_flag={minor_n} ({minor_n/n:.1%})")
print(f"cont_echo={echo_n}/{cont_n} ({echo_n/max(cont_n,1):.3f})")
print(f"resp_len avg={sum(resp_lens)//len(resp_lens)} min={min(resp_lens)} max={max(resp_lens)}")

# 2) 低覆盖率文件
cov = json.load(open(COV, encoding="utf-8"))
low = [x for x in cov["per_file"] if x.get("coverage", 1) < 0.25]
print(f"\nlow_coverage(<25%)={len(low)}")
for x in low:
    print(f"  {x['rel']}  cov={x['coverage']:.2%}  skip={x['skipped_windows']}/{x['windows_total']}")

# 3) 抽 3 条样本看结构
print("\n=== 3 sample previews ===")
with open(V3, encoding="utf-8") as f:
    lines = [next(f) for _ in range(3)]
    for i, ln in enumerate(lines):
        r = json.loads(ln)
        m = r["meta"]
        u = r["messages"][0]["content"]
        a = r["messages"][1]["content"]
        print(f"\n--- sample {i} ---")
        print(f"  stype={m['stype']} minor={m['minor_flag']} ip={m['ip_fanfic']} level={m['level']}")
        print(f"  user[:120]={u[:120]!r}")
        print(f"  assistant[:120]={a[:120]!r}")
        print(f"  resp_len={len(a)}")
