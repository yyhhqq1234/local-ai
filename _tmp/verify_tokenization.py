# -*- coding: utf-8 -*-
"""用真实 tokenizer 编码 NSFW 正文：确认无 UNK、可往返"""
import os, json

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
DATA = os.path.join(TRAIN, "data")

try:
    from transformers import AutoTokenizer
except Exception as e:
    print(f"[MISS] transformers 未装: {e}")
    raise SystemExit

# 用 base-meta 的 tokenizer（训练基座同源）
tok = AutoTokenizer.from_pretrained(os.path.join(TRAIN, "kitty-rev", "deploy", "base-meta"))
unk_id = tok.unk_token_id
print(f"tokenizer 加载 OK, unk_id={unk_id}, vocab_size={tok.vocab_size}")

# 取 mix-nsfw 前 20 条 assistant 正文
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
        if len(texts) >= 20:
            break

total_chars = 0
total_tokens = 0
unk_count = 0
roundtrip_fail = 0
for t in texts:
    ids = tok.encode(t, add_special_tokens=False)
    total_chars += len(t)
    total_tokens += len(ids)
    unk_count += sum(1 for i in ids if i == unk_id)
    # 往返校验
    dec = tok.decode(ids, skip_special_tokens=True)
    if dec != t:
        roundtrip_fail += 1

print(f"\n编码 {len(texts)} 条 NSFW 正文:")
print(f"  字符 {total_chars:,}  →  token {total_tokens:,}  (压缩比 {total_chars/max(total_tokens,1):.2f})")
print(f"  UNK token 总数: {unk_count}")
print(f"  往返不一致: {roundtrip_fail}/{len(texts)}")
print("\n[DONE]")
