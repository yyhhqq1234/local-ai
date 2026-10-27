# -*- coding: utf-8 -*-
"""检查：1) mix-nsfw.jsonl 中 assistant 文本是否含 NSFW 正文  2) 词表是否存在并覆盖 NSFW 词"""
import os, json, glob

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
DATA = os.path.join(BASE, "train", "data")
TRAIN = os.path.join(BASE, "train")

# --- 1) 文本内容检查 ---
fp = os.path.join(DATA, "mix-nsfw.jsonl")
n = 0
asst_chars = 0
sample_lines = []
with open(fp, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            o = json.loads(line)
            msgs = o.get("messages", [])
            for m in msgs:
                if m.get("role") == "assistant":
                    c = len(m.get("content", ""))
                    asst_chars += c
                    if len(sample_lines) < 3 and c > 200:
                        sample_lines.append((m["content"][:120], c))
        except Exception:
            pass

print(f"[1] mix-nsfw.jsonl: {n} 行, assistant 总字符 {asst_chars:,}")
print(f"    平均 assistant 长度 {asst_chars/max(n,1):,.0f} 字符/条")
for s, c in sample_lines:
    print(f"    样例({c}字符): {s!r}")

# --- 2) 词表检查 ---
print("\n[2] 词表文件搜索:")
vocab_found = []
for pat in ["**/vocab*", "**/tokenizer*", "**/*tokenizer*json", "**/merges*", "**/tokenization*"]:
    for p in glob.glob(os.path.join(TRAIN, "**", pat), recursive=True):
        if os.path.isfile(p):
            vocab_found.append(p)
for p in sorted(set(vocab_found)):
    rel = os.path.relpath(p, BASE)
    print(f"    {os.path.getsize(p):>12,}  {rel}")
