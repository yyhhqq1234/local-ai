# -*- coding: utf-8 -*-
"""fix_jsonl_quotes.py —— 修复 JSONL 里"正文含裸 ASCII 双引号"导致的解析失败

场景：手写知识库时正文里用了 "…" 之类的直引号，破坏 JSON 字符串边界。
做法：先把 4 个字段分隔符替换成哨兵，正文里剩余的 " 交替替换为 「 」，再还原分隔符；
      逐行 json.loads 验证，仍失败的行原样保留并打印行号（人工处理）。
"""
import json
import sys

DELIMS = ['"topic":"', '","q":"', '","a":"', '","kitty":"', '"}', '","a":"']
SENT = {"\"topic\":\"": "\x01T\x01", "\",\"q\":\"": "\x01Q\x01",
        "\",\"a\":\"": "\x01A\x01", "\",\"kitty\":\"": "\x01K\x01", "\"}": "\x01E\x01"}


def repair(line):
    s = line
    # 先把已转义的引号 \" 换成哨兵（否则会留下 \「 这种非法转义）
    s = s.replace('\\"', "\x02")
    for k, v in SENT.items():
        s = s.replace(k, v)
    if s.startswith("{"):
        s = s[1:]
    out, open_q = [], True
    for ch in s:
        if ch == '"' or ch == "\x02":
            out.append("「" if open_q else "」")
            open_q = not open_q
        else:
            out.append(ch)
    s = "".join(out)
    for k, v in SENT.items():
        s = s.replace(v, k)
    if not s.startswith("{"):
        s = "{" + s
    return s


def main(path):
    rows, fixed, failed = [], 0, []
    with open(path, "r", encoding="utf-8") as f:
        for i, raw in enumerate(f, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                json.loads(line)
                rows.append(line)
                continue
            except json.JSONDecodeError:
                pass
            cand = repair(line)
            try:
                json.loads(cand)
                rows.append(cand)
                fixed += 1
            except json.JSONDecodeError as e:
                failed.append((i, str(e)[:50]))
                rows.append(line)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r + "\n")
    print(f"{path}: kept={len(rows)} repaired={fixed} still_bad={len(failed)}")
    for i, e in failed[:10]:
        print(f"  line {i}: {e}")
    return len(failed)


if __name__ == "__main__":
    sys.exit(1 if main(sys.argv[1]) else 0)
