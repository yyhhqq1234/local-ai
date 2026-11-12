import json
from collections import Counter

path = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v4.jsonl"

missing_id = []
missing_meta = []
replacement_char = []
empty_content = []
short_content = []  # assistant content < 100 chars

with open(path, "r", encoding="utf-8") as f:
    for line_no, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        
        if "id" not in rec:
            missing_id.append(line_no)
        if "meta" not in rec:
            missing_meta.append(line_no)
        
        for i, msg in enumerate(rec.get("messages", [])):
            content = msg.get("content", "")
            if "\ufffd" in content:
                replacement_char.append((line_no, i))
            if len(content.strip()) == 0:
                empty_content.append((line_no, i))
            if msg.get("role") == "assistant" and len(content) < 100:
                short_content.append((line_no, len(content)))

print(f"missing id: {len(missing_id)}")
print(f"  first 10: {missing_id[:10]}")
print(f"missing meta: {len(missing_meta)}")
print(f"  first 10: {missing_meta[:10]}")
print(f"\\ufffd: {len(replacement_char)}")
print(f"  first 10: {replacement_char[:10]}")
print(f"empty content: {len(empty_content)}")
print(f"  first 10: {empty_content[:10]}")
print(f"short assistant (<100): {len(short_content)}")
print(f"  first 10: {short_content[:10]}")

# 看一条有 \ufffd 的具体内容
if replacement_char:
    ln, idx = replacement_char[0]
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if i == ln:
                rec = json.loads(line)
                content = rec["messages"][idx]["content"]
                # 找 \ufffd 位置
                pos = content.find("\ufffd")
                ctx = content[max(0,pos-30):pos+30]
                print(f"\nFirst \\ufffd at line {ln} msg[{idx}]:")
                print(f"  context: ...{ctx}...")
                break
