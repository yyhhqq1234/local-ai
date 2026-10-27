# -*- coding: utf-8 -*-
"""用 tokenizers 库直接加载 tokenizer.json 编码 NSFW 正文：无 UNK、可往返"""
import os, json

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
TRAIN = os.path.join(BASE, "train")
DATA = os.path.join(TRAIN, "data")

try:
    from tokenizers import Tokenizer
except Exception as e:
    print(f"[MISS] tokenizers 未装: {e}")
    raise SystemExit

# base-meta 的 tokenizer.json（训练基座同源）
tk = Tokenizer.from_file(os.path.join(TRAIN, "kitty-rev", "deploy", "base-meta", "tokenizer.json"))
vocab_size = tk.get_vocab_size()
unk_id = tk.token_to_id("<unk>") if "<unk>" in tk.get_vocab() else None
print(f"tokenizer 加载 OK, vocab_size={vocab_size}, unk_id={unk_id}")

# 取 mix-nsfw 前 50 条 assistant 正文
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
        if len(texts) >= 50:
            break

total_chars = 0
total_tokens = 0
unk_count = 0
roundtrip_fail = 0
for t in texts:
    ids = tk.encode(t).ids
    total_chars += len(t)
    total_tokens += len(ids)
    unk_count += sum(1 for i in ids if i == unk_id)
    dec = tk.decode(ids)
    if dec != t:
        roundtrip_fail += 1

print(f"\n编码 {len(texts)} 条 NSFW 正文:")
print(f"  字符 {total_chars:,}  →  token {total_tokens:,}  (压缩比 {total_chars/max(total_tokens,1):.3f})")
print(f"  UNK token 总数: {unk_count}")
print(f"  往返不一致: {roundtrip_fail}/{len(texts)}")
print("\n[DONE]")
