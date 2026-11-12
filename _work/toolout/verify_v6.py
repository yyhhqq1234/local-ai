import json, sys
from collections import Counter

path = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v6.jsonl"

errors = []
total = 0
role_counter = Counter()
msg_count = Counter()
level_counter = Counter()
stype_counter = Counter()

with open(path, "r", encoding="utf-8") as f:
    for line_no, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"Line {line_no}: JSON parse error: {e}")
            continue
        for field in ["id", "messages", "meta"]:
            if field not in rec:
                errors.append(f"Line {line_no}: missing '{field}'")
        msgs = rec.get("messages", [])
        msg_count[len(msgs)] += 1
        for i, msg in enumerate(msgs):
            role = msg.get("role")
            content = msg.get("content")
            role_counter[role] += 1
            if not isinstance(content, str):
                errors.append(f"Line {line_no} msg[{i}]: content not str")
                continue
            if "\ufffd" in content:
                errors.append(f"Line {line_no} msg[{i}]: replacement char")
        meta = rec.get("meta", {})
        if "level" in meta:
            level_counter[meta["level"]] += 1
        if "stype" in meta:
            stype_counter[meta["stype"]] += 1

report = [
    f"=== nsfw-train-v6.jsonl FINAL VERIFICATION ===",
    f"total records: {total}",
    f"errors: {len(errors)}",
    f"",
    f"msg count dist: {dict(msg_count)}",
    f"role dist: {dict(role_counter)}",
    f"level dist: {dict(level_counter)}",
    f"stype dist: {dict(stype_counter)}",
]
if errors:
    report.append("")
    report.append("--- ERRORS (first 20) ---")
    for e in errors[:20]:
        report.append(f"  {e}")
else:
    report.append("")
    report.append("PASS: zero errors")

text = "\n".join(report)
with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\verify_v6_report.txt", "w", encoding="utf-8") as f:
    f.write(text)

for line in report:
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode())

sys.exit(1 if errors else 0)
