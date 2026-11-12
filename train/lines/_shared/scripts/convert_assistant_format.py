# -*- coding: utf-8 -*-
"""P1-b · assistant 首行格式归一化：文档句式 → 可执行调用

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
P0 诊断结论（2026-10-28，21 条参数错逐条看原文后确认）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
档3 在 40 条泛化集上「参数错」21 条，看 resp 原文，18 条长这样：

    kitty_die — action 取 scan：
    kitty_dump — action 取 dump / unmap：
    kitty_acescan — action 取 acescan：
    kitty_selftest — action 取 a / c / e / all：

值全写对了，但用的是「工具 — action 取 A / B / C」这种**文档枚举句式**，
而可执行的调用格式是 `kitty_die action=scan`。

追到训练集（core + coverage 5811 条）实测：
    632 条  纯 enum 格式（`工具 — action 取 A/B/C`，不可执行）   ← 10.9%
   1442 条  纯 exec 格式（`action=A`，可执行）                    ← 24.8%
   3737 条  纯文字（概念解释，不涉及调用）                         ← 64.3%
enum 格式涉及 **全部 64 个工具**，不是个别现象。

即：模型是**忠实地模仿了训练集的格式**，不是不知道 action 值。
真实缺陷成立（输出无法被 tool-call 解析），但根因在数据格式不在模型能力。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
转换规则（不删任何内容，只改表达形式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
单值：
    kitty_sym — action 取 exports：            → kitty_sym action=exports：
多值：
    kitty_sym — action 取 exports/imports/resolve：
        → kitty_sym action=exports
          （action 可取 exports / imports / resolve；本次走 exports）：
其余行（选择理由 / 操作要点 / 判据）逐字保留。

多值取第一个作为主 action —— 训练集写法上第一个就是主用值。

用法：
  python convert_assistant_format.py --dry-run
  python convert_assistant_format.py --src train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v2-aug.jsonl \
      --out train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-format.jsonl
"""
import argparse
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None

DATA = os.path.join(_L9B, "data", "kitty-reverse")

# 训练集真实格式：`kitty_sym \u2014 action \u53d6 exports / imports / resolve\uff1a`
#   \u2014 = EM DASH（不是「的」—— 这一点踩过一次，用 \u7684 统计出 0 条）
PAT_ENUM = re.compile(
    r"((?:kitty|reverse)_[a-z0-9_]+)\s*[\u2014\u2013\-]+\s*action\s*\u53d6\s*([^\uff1a:\n]+)[\uff1a:]?"
)
PAT_EXEC = re.compile(r"((?:kitty|reverse)_[a-z0-9_]+)\s+action\s*=\s*([a-z0-9_\-]+)")


def parse_vals(raw):
    """'scan / status' → ['scan','status']；保留原顺序"""
    parts = re.split(r"[/\uff0f\u3001,]", raw)
    out = [p.strip().strip("\u3002\u3001 ") for p in parts if p.strip()]
    return [p for p in out if p]


def convert_one(text):
    """返回 (新文本, 是否改动, 工具名, 主 action, 枚举值个数)"""
    m = PAT_ENUM.search(text)
    if not m:
        return text, False, None, None, 0
    if PAT_EXEC.search(text[:m.end()]):
        # 同一行里已经有可执行格式，不重复加
        return text, False, m.group(1), None, 0
    tool = m.group(1)
    vals = parse_vals(m.group(2))
    if not vals:
        return text, False, tool, None, 0
    main = vals[0]
    tail = ""
    nxt = text[m.end():m.end() + 1]
    if nxt == "\uff1a" or nxt == ":":
        tail = nxt
    if len(vals) == 1:
        new = "%s action=%s" % (tool, main)
    else:
        new = "%s action=%s\n\uff08action \u53ef\u53d6 %s\uff1b\u672c\u6b21\u8d70 %s\uff09" % (
            tool, main, " / ".join(vals), main)
    # 只替换匹配段（含尾冒号），其余逐字保留
    out = text[:m.start()] + new + tail + text[m.end() + (1 if tail else 0):]
    return out, True, tool, main, len(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(DATA, "train-kitty-v2-aug.jsonl"))
    ap.add_argument("--out", default=os.path.join(DATA, "train-kitty-v3-format.jsonl"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print("=" * 78)
    print("assistant 首行格式归一化 —— \u6587\u6863\u53e5\u5f0f \u2192 \u53ef\u6267\u884c\u8c03\u7528")
    print("=" * 78)
    print("src: %s" % args.src)

    n = changed = 0
    single = multi = 0
    tools = {}
    rows = []
    with io.open(args.src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            o = json.loads(line)
            hit = False
            for m in o.get("messages") or []:
                if m.get("role") != "assistant":
                    continue
                new, ok, tool, main, nv = convert_one(m.get("content") or "")
                if ok:
                    hit = True
                    m["content"] = new
                    tools[tool] = tools.get(tool, 0) + 1
                    if nv <= 1:
                        single += 1
                    else:
                        multi += 1
                break
            if hit:
                changed += 1
            rows.append(o)

    print("扫描 %d 条 | 改动 %d 条（%.1f%%）" % (n, changed, 100.0 * changed / max(n, 1)))
    print("  单值枚举 %d | 多值枚举 %d" % (single, multi))
    print("  涉及工具 %d 个" % len(tools))
    for k, v in sorted(tools.items(), key=lambda x: -x[1])[:10]:
        print("    %-26s %d" % (k, v))

    if args.dry_run:
        print("\n[dry-run] 样例（前 2 条改动）：")
        shown = 0
        for o in rows:
            a = next((m["content"] for m in o["messages"] if m["role"] == "assistant"), "")
            if "action=" in a:
                print("  ---")
                print("  " + a[:200].replace("\n", "\n  "))
                shown += 1
                if shown >= 2:
                    break
        return

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("\n\u2192 \u843d\u76d8 %s\uff08%d \u6761\uff0c\u4e0e\u6e90\u540c\u6570\uff09" % (args.out, len(rows)))


if __name__ == "__main__":
    main()
