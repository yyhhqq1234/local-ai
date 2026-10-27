# -*- coding: utf-8 -*-
"""精确定位 HF tokenizer 词表数据文件 + 检查是否覆盖 NSFW 高频词"""
import os, json, glob

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")

# 1) 精确文件名搜索
TARGETS = ["vocab.json", "tokenizer.json", "merges.txt", "special_tokens_map.json"]
found = []
for root, dirs, files in os.walk(TRAIN):
    # 跳过 venv / 源码目录
    if any(x in root for x in [r"\.venv", r"\third_party", r"\include", r"\cpp"]):
        continue
    for fn in files:
        if fn in TARGETS:
            fp = os.path.join(root, fn)
            found.append((fp, os.path.getsize(fp)))

print("=== 词表数据文件 ===")
if not found:
    print("  [MISS] 未找到 vocab.json / tokenizer.json / merges.txt")
else:
    for fp, size in sorted(found):
        rel = os.path.relpath(fp, BASE)
        print(f"  {size:>12,}  {rel}")

# 2) 若有 vocab.json，检查 NSFW 高频词覆盖率
vocab_files = [fp for fp, _ in found if os.path.basename(fp) == "vocab.json"]
if vocab_files:
    vp = vocab_files[0]
    try:
        vocab = json.load(open(vp, "r", encoding="utf-8"))
        ids = set(vocab.keys())
        print(f"\n  vocab 大小: {len(ids)}")
        # NSFW 高频词样本
        nsfw_words = ["扭动", "呻吟", "颤抖", "湿润", "柔软", "紧致", "喘息", "汗水",
                      "脸颊", "呼吸", "低吟", "情欲", "快感", "酥麻", "敏感", "饱满"]
        hit = [w for w in nsfw_words if w in ids]
        miss = [w for w in nsfw_words if w not in ids]
        print(f"  NSFW 高频词直接命中: {len(hit)}/{len(nsfw_words)}")
        print(f"  未直接命中(可能由子词拼成): {miss}")
    except Exception as e:
        print(f"  [ERR] 读 vocab: {e}")
