"""
修复 nsfw-train-v4.jsonl 的问题：
1. 缺 id → 补 auto_id_NNNN
2. 缺 meta → 补空 meta（或从上下文推断）
3. \ufffd 乱码 → 删除该条（不可恢复）
4. assistant content < 10 字符 → 标记为可疑（不删，只报告）
输出: nsfw-train-v5.jsonl（清洗后）+ 修复报告
"""
import json, re
from collections import Counter

src = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v4.jsonl"
dst = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v5.jsonl"

# 统计
stats = Counter()
removed_lines = []
fixed_lines = []

# 先读全部，找到最大 id 数字
max_id_num = 0
all_recs = []
with open(src, "r", encoding="utf-8") as f:
    for line_no, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        all_recs.append((line_no, rec))
        # 提取 id 数字
        rid = rec.get("id", "")
        m = re.search(r'(\d+)$', str(rid))
        if m:
            max_id_num = max(max_id_num, int(m.group(1)))

print(f"Total records: {len(all_recs)}")
print(f"Max id number: {max_id_num}")

next_id = max_id_num + 1
clean_count = 0

with open(dst, "w", encoding="utf-8") as out:
    for line_no, rec in all_recs:
        # 1) 缺 id
        if "id" not in rec:
            rec["id"] = f"auto_{next_id:06d}"
            next_id += 1
            stats["missing_id_fixed"] += 1
            fixed_lines.append((line_no, "added id"))
        
        # 2) 缺 meta
        if "meta" not in rec:
            rec["meta"] = {}
            stats["missing_meta_fixed"] += 1
            fixed_lines.append((line_no, "added empty meta"))
        
        # 3) \ufffd 检查
        has_replacement = False
        for msg in rec.get("messages", []):
            content = msg.get("content", "")
            if "\ufffd" in content:
                has_replacement = True
                break
        
        if has_replacement:
            stats["removed_ufffd"] += 1
            removed_lines.append(line_no)
            continue  # 跳过这条
        
        # 4) 短 assistant 检查
        for msg in rec.get("messages", []):
            if msg.get("role") == "assistant":
                content = msg.get("content", "").strip()
                if len(content) < 10:
                    stats["short_assistant"] += 1
                    break
        
        # 写入
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        clean_count += 1

# 报告
report = [
    f"=== 修复报告 ===",
    f"原始记录数: {len(all_recs)}",
    f"写入记录数: {clean_count}",
    f"删除（\\ufffd 乱码）: {stats['removed_ufffd']}",
    f"补充 id: {stats['missing_id_fixed']}",
    f"补充 meta: {stats['missing_meta_fixed']}",
    f"短 assistant (<10字符): {stats['short_assistant']}",
    f"",
    f"删除的行号 (前 20): {removed_lines[:20]}",
]

report_text = "\n".join(report)
print(report_text)

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\fix_report.txt", "w", encoding="utf-8") as f:
    f.write(report_text)

print(f"\nOutput: {dst}")
