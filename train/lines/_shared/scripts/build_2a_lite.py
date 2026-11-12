#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_2a_lite.py — 把 2A 侧压成「短、干净、禁工具」的轻量集（保护 kitty 主线）

## 依据操作者 2026-10-30 16:4x 指示
「适当减少长上下文的训练内容，先保住核心的 kitty 逆向工作台内容。」

⇒ 策略：
   · kitty 段**一条不动**（23718 行，P50 200 字符，本身就是短样本）
   · 2A 段从 1401 字符（P50）压到 **<= 900**，并提高其梯度份额占比的可控性
   · 长样本（>1200 字符）在混合集里的占比作为显式指标报告，目标是压到 10% 以下

输入 = P0 已产出的两档（都带「禁工具」system、都是评测形态提问）：
      train/lines/9b-oxcoder/data/agent-traj/traj-2a-evalshape-t1.jsonl   162 行（文件+函数都真实）
      train/lines/9b-oxcoder/data/agent-traj/traj-2a-evalshape-t2.jsonl   987 行（只有真实文件）
输出 = train/lines/9b-oxcoder/data/agent-traj/traj-2a-lite.jsonl

截断规则（保结构，不保长度）：
   1. 先保围栏代码块：从代码头取行，累计不超 60% 预算
   2. 再保总结头部：剩余预算给根因/改法描述
   3. 硬尾：整条答案不超 --max-ans（默认 900）
"""
import argparse
import io
import json
import os
import random
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T1 = os.path.join(ROOT, "data", "agent-traj", "traj-2a-evalshape-t1.jsonl")
T2 = os.path.join(ROOT, "data", "agent-traj", "traj-2a-evalshape-t2.jsonl")
OUT = os.path.join(ROOT, "data", "agent-traj", "traj-2a-lite.jsonl")

FENCE_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.S)


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", [])
                   if m.get("role") == "assistant")


def truncate(ans, max_ans):
    """先压代码，再压正文。"""
    if len(ans) <= max_ans:
        return ans
    m = FENCE_BLOCK.search(ans)
    if not m:
        return ans[:max_ans].rsplit("\n", 1)[0]
    code = m.group(1)
    head = ans[:m.start()].strip()
    tail = ans[m.end():].strip()
    code_budget = int(max_ans * 0.6)
    lines, used = [], 0
    for ln in code.split("\n"):
        if used + len(ln) + 1 > code_budget:
            lines.append("# ...(truncated)")
            break
        lines.append(ln)
        used += len(ln) + 1
    code_t = "\n".join(lines)
    head_budget = max(120, max_ans - used - 30)
    head_t = head[:head_budget].rstrip()
    out = head_t + "\n\n```python\n" + code_t + "\n```"
    if len(out) > max_ans:
        out = out[:max_ans].rsplit("\n", 1)[0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-ans", type=int, default=900)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rows, seen = [], 0
    for p in (T1, T2):
        if not os.path.isfile(p):
            print("[skip] 缺 %s" % p)
            continue
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            seen += 1
            a = asst(o)
            if a.count("```") < 2:
                continue
            o["messages"][-1]["content"] = truncate(a, args.max_ans)
            o["meta"]["max_ans"] = args.max_ans
            rows.append(o)

    random.Random(args.seed).shuffle(rows)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fo:
        for o in rows:
            fo.write(json.dumps(o, ensure_ascii=False) + "\n")

    L = sorted(len(asst(o)) for o in rows)
    tc = sum(1 for o in rows if "<tool_call>" in asst(o))
    code = sum(1 for o in rows if asst(o).count("```") >= 2)
    chars = sum(L)
    print("[in ] %d 行 → 产出 %d 行" % (seen, len(rows)))
    print("      assistant 字符 %d（P50 %d / P90 %d / max %d）"
          % (chars, L[len(L) // 2], L[int(len(L) * .9)], L[-1]))
    print("      代码围栏 %d/%d · tool_call %d（须 0）· >1200 字符 %d 行"
          % (code, len(rows), tc, sum(1 for x in L if x > 1200)))
    print("      → %s" % args.out)


if __name__ == "__main__":
    main()
