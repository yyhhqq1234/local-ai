# -*- coding: utf-8 -*-
"""纯 Python：检查 vocab.json 是否覆盖 NSFW 正文全部字符"""
import os, json

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
DATA = os.path.join(TRAIN, "data")

# 加载 vocab
vp = os.path.join(TRAIN, "kitty-rev", "deploy", "base-meta", "vocab.json")
vocab = json.load(open(vp, "r", encoding="utf-8"))
print(f"vocab 大小: {len(vocab)}")

# 取 mix-nsfw 前 100 条 assistant 正文
fp = os.path.join(DATA, "mix-nsfw.jsonl")
texts = []
with open(fp, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        for m in o["messages"]:
            if m.get("role") == "assistant":
                texts.append(m["content"])
        if len(texts) >= 100:
            break

# 逐字符检查
all_chars = set()
missing_chars = {}
for t in texts:
    for ch in t:
        all_chars.add(ch)
        if ch not in vocab:
            missing_chars[ch] = missing_chars.get(ch, 0) + 1

total_chars = sum(len(t) for t in texts)
covered = total_chars - sum(missing_chars.values())

print(f"\n{len(texts)} 条 NSFW 正文, 共 {total_chars:,} 字符")
print(f"  唯一字符数: {len(all_chars)}")
print(f"  已覆盖字符: {covered:,} / {total_chars:,}  ({covered/total_chars:.4%})")
print(f"  缺失字符种类: {len(missing_chars)}")
if missing_chars:
    # 按频率排序显示前 20
    top_missing = sorted(missing_chars.items(), key=lambda x: -x[1])[:20]
    print(f"  缺失字符 TOP20:")
    for ch, cnt in top_missing:
        print(f"    {repr(ch):10s} x{cnt}")
else:
    print(f"  [OK] 全部字符在 vocab 中，BPE 编码无 UNK")
print("\n[DONE]")
