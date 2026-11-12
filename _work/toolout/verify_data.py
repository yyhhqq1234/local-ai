"""
验证 nsfw-train-v4.jsonl 数据正确性
检查项：
1. 每行能被 json.loads 解析
2. 每条记录有 id/messages/meta
3. messages 结构正确（role + content）
4. content 无乱码（\ufffd 替换字符、非预期控制字符）
5. UTF-8 编码完整性
6. meta 字段一致性
"""
import json, sys
from collections import Counter

path = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\data\nsfw-train-v4.jsonl"

errors = []
warnings = []
stats = {"total": 0, "ok": 0}

# 角色统计
role_counter = Counter()
msg_count_counter = Counter()

with open(path, "r", encoding="utf-8") as f:
    for line_no, line in enumerate(f, 1):
        line = line.strip()
        if not line:
            continue
        
        stats["total"] += 1
        
        # 1) JSON 解析
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"Line {line_no}: JSON parse error: {e}")
            continue
        
        # 2) 必需字段
        for field in ["id", "messages", "meta"]:
            if field not in rec:
                errors.append(f"Line {line_no}: missing '{field}'")
        
        # 3) messages 结构
        msgs = rec.get("messages", [])
        msg_count_counter[len(msgs)] += 1
        for i, msg in enumerate(msgs):
            role = msg.get("role")
            content = msg.get("content")
            role_counter[role] += 1
            
            if role not in ("system", "user", "assistant"):
                warnings.append(f"Line {line_no} msg[{i}]: unexpected role '{role}'")
            
            if not isinstance(content, str):
                errors.append(f"Line {line_no} msg[{i}]: content is not str")
                continue
            
            # 4) 乱码检查
            if "\ufffd" in content:
                errors.append(f"Line {line_no} msg[{i}]: contains \\ufffd replacement char")
            
            # 非预期控制字符（排除 \n \r \t）
            ctrl_chars = [c for c in content if ord(c) < 32 and c not in ("\n", "\r", "\t")]
            if ctrl_chars:
                warnings.append(f"Line {line_no} msg[{i}]: {len(ctrl_chars)} control chars")
            
            # 空内容
            if len(content.strip()) == 0:
                warnings.append(f"Line {line_no} msg[{i}]: empty content")
        
        # 5) meta 一致性
        meta = rec.get("meta", {})
        if "topic" in meta and not isinstance(meta["topic"], list):
            errors.append(f"Line {line_no}: meta.topic is not list")
        if "level" in meta and meta["level"] not in ("L1", "L2", "L3"):
            warnings.append(f"Line {line_no}: meta.level='{meta['level']}' (expected L1/L2/L3)")
        
        stats["ok"] += 1

# 输出报告
report = []
report.append(f"=== 数据验证报告 ===")
report.append(f"总行数: {stats['total']}")
report.append(f"通过: {stats['ok']}")
report.append(f"错误: {len(errors)}")
report.append(f"警告: {len(warnings)}")
report.append(f"")
report.append(f"消息数分布: {dict(msg_count_counter)}")
report.append(f"角色分布: {dict(role_counter)}")
report.append(f"")

if errors:
    report.append(f"--- 错误详情 (前 20) ---")
    for e in errors[:20]:
        report.append(f"  {e}")
else:
    report.append("--- 无错误 ---")

if warnings:
    report.append(f"--- 警告详情 (前 20) ---")
    for w in warnings[:20]:
        report.append(f"  {w}")
else:
    report.append("--- 无警告 ---")

report_text = "\n".join(report)
print(report_text)

with open(r"D:\BaiduNetdiskDownload\Local-AI\_work\toolout\verify_report.txt", "w", encoding="utf-8") as f:
    f.write(report_text)

# 退出码：有错误则 1
sys.exit(1 if errors else 0)
