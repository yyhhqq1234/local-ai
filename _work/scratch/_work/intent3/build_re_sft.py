# -*- coding: utf-8 -*-
"""校验并生成 re-sft（规范路径：train/lines/27b-kittyrev/kitty-rev/data/intent3/）。
输出两份：re-sft.jsonl（id/prompt/response/meta）+ re-sft.messages.jsonl（训练侧 messages 格式）。
门禁：id 唯一 / 长度 200-500 / 工具名 ⊆ contracts(64) / 每条 ≥2 判据 / prompt 唯一 / 合同外工具显式标注。
"""
import json
import re
import sys

sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\_work\intent3")
import re1, re2, re3, re4

D = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\data\intent3"
OUT = D + r"\re-sft.jsonl"
MSG_OUT = D + r"\re-sft.messages.jsonl"
CONTRACTS = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\contracts\tools.json"

# 合同外工具：kitty 工具箱没有转储/文件系统解析能力，硬套 kitty_* 会写错判据。
# 只允许这两个，且逐条写进 meta.tools_external。
EXTERNAL_RE = re.compile(r"\b(cdb|unsquashfs)\b")
EXTERNAL_WHY = "kitty 无转储/文件系统解析工具，硬套会写错判据"

contract = json.load(open(CONTRACTS, encoding="utf-8"))
valid = {t["name"] for t in contract["tools"]}
assert len(valid) == 64, len(valid)

records = re1.RECORDS + re2.RECORDS + re3.RECORDS + re4.RECORDS
errors = []
ids, prompts = set(), set()

TOOL_RE = re.compile(r"((?:kitty|reverse)_[a-z0-9_]+)")

for r in records:
    rid = r["id"]
    if rid in ids:
        errors.append(f"{rid}: id 重复")
    ids.add(rid)
    if r["prompt"] in prompts:
        errors.append(f"{rid}: prompt 重复")
    prompts.add(r["prompt"])

    body = r["response"]
    n = len(body)
    if not (200 <= n <= 500):
        errors.append(f"{rid}: 长度 {n} 不在 200-500")

    names = set(TOOL_RE.findall(body))
    bad = sorted(n for n in names if n not in valid)
    if bad:
        errors.append(f"{rid}: 非合同工具名 {bad}")
    if not names:
        errors.append(f"{rid}: 没有 kitty_* 工具调用")

    cmd_lines = sum(1 for ln in body.splitlines()
                    if ln.strip().startswith(("kitty_", "reverse_", "cdb", "unsquashfs")))
    hexes = len(re.findall(r"0x[0-9A-Fa-f]{2,}", body))
    if cmd_lines < 1 or (cmd_lines + hexes) < 2:
        errors.append(f"{rid}: 可执行判据不足（cmd_lines={cmd_lines}, hex={hexes}）")
    if "判据一" not in body or "判据二" not in body:
        errors.append(f"{rid}: 判据一/判据二 标注缺失")

if errors:
    print(f"FAIL {len(errors)} 条：")
    for e in errors[:40]:
        print(" -", e)
    sys.exit(1)

ext_rows = []
with open(OUT, "w", encoding="utf-8") as f, open(MSG_OUT, "w", encoding="utf-8") as fm:
    for r in records:
        meta = {
            "forge": "r2w",
            "group": "re-sft",
            "topic": r["topic"],
            "tools": sorted(set(TOOL_RE.findall(r["response"]))),
        }
        ext = sorted(set(EXTERNAL_RE.findall(r["response"])))
        if ext:
            meta["tools_external"] = ext
            meta["why_external"] = EXTERNAL_WHY
            ext_rows.append((r["id"], ext))
        row = {"id": r["id"], "prompt": r["prompt"], "response": r["response"], "meta": meta}
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        msg = {
            "id": r["id"],
            "messages": [
                {"role": "user", "content": r["prompt"]},
                {"role": "assistant", "content": r["response"]},
            ],
            "meta": meta,
        }
        fm.write(json.dumps(msg, ensure_ascii=False) + "\n")

lens = sorted(len(r["response"]) for r in records)
print(f"OK {len(records)} 条 -> {OUT}")
print(f"OK messages {len(records)} 条 -> {MSG_OUT}")
print(f"len min/median/max = {lens[0]}/{lens[len(lens)//2]}/{lens[-1]}")
print(f"合同外工具行 {len(ext_rows)} 条：{ext_rows}")
assert len(ext_rows) == 11, f"外部工具行数变了: {len(ext_rows)}"
