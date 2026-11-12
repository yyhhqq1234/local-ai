#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
2B 门控 v4b：从 JSON 题目库生成训练集（题目与代码分离，避免转义问题）

与 v4 的区别：
  v4 的 normal 桶直接抄了评测集原文 20 条（9 条 trap 全部命中）→ 严重泄漏
  v4b 的题目全部换成与评测集不重合的题面（考察点保留），并在生成时做泄漏校验

输入 train-2b-gated-v3b.jsonl（无泄漏的基础集）
      + _2b_v4_topics.json（22 道换过题面的 normal 题）
      + 评测集（只用于泄漏校验，不参与生成）
"""
import io, json, os, random, re, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", "nsfw-gated", "train-2b-gated-v3b.jsonl")
TOPICS = os.path.join(HERE, "_2b_v4_topics.json")
OUT = os.path.join(HERE, "data", "nsfw-gated", "train-2b-gated-v4b.jsonl")
TRAIN_OUT = os.path.join(HERE, "data", "nsfw-gated", "train-2b-gated-v4b-train.jsonl")
EVAL_DIR = os.path.join(HERE, "data", "eval")

SYS_NORMAL = "模式：常规（未授权成人向内容）。不含露骨性描写。"
SEED = 20251105
REPEAT = 20

PHRASES = [
    "{q}",
    "请说明：{q}",
    "{q}（讲清楚就行，不用展开太多）",
    "{q} —— 直接说要点。",
    "有个问题想确认：{q}",
    "{q} 这个我一直没搞明白，给讲讲。",
]


def load_eval_users():
    s = set()
    for sub in ("val", "test"):
        d = os.path.join(EVAL_DIR, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.endswith(".jsonl"):
                continue
            for line in io.open(os.path.join(d, fn), encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                for m in r.get("messages", []):
                    if m.get("role") == "user":
                        s.add(m["content"].strip())
                        break
    return s


def main():
    random.seed(SEED)
    base = [json.loads(l) for l in io.open(SRC, encoding="utf-8") if l.strip()]
    print(f"[IN ] 基础集 v3b {len(base)} 条")

    tp = json.load(io.open(TOPICS, encoding="utf-8"))
    pools = {k: v for k, v in tp.items() if not k.startswith("_")}
    n_topic = sum(len(v) for v in pools.values())
    print(f"[IN ] 题目库 {n_topic} 题（A {len(pools['A_knowledge'])} · "
          f"B {len(pools['B_technical'])} · C {len(pools['C_discuss'])}）")

    ev = load_eval_users()
    print(f"[IN ] 评测集 user 共 {len(ev)} 条（用于泄漏校验）")

    rows = []
    for tag, items in pools.items():
        for q, a in items:
            for ph in PHRASES:
                qq = ph.format(q=q)
                if qq.strip() in ev:
                    print(f"  [SKIP 泄漏] {qq[:50]}")
                    continue
                rows.append({"messages": [
                    {"role": "system", "content": SYS_NORMAL},
                    {"role": "user", "content": qq},
                    {"role": "assistant", "content": a}]})
    print(f"[NEW] 生成 {len(rows)} 条（×{REPEAT} 提权 → {len(rows)*REPEAT}）")

    allrows = base + rows * REPEAT
    random.shuffle(allrows)

    # 输出分析版（带 meta 便于追溯）
    with io.open(OUT, "w", encoding="utf-8") as f:
        for r in allrows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # 输出训练版（纯 messages，datasets 能稳定加载）
    with io.open(TRAIN_OUT, "w", encoding="utf-8") as f:
        for r in allrows:
            f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")

    print(f"[OUT] {OUT}  {len(allrows)} 行")
    print(f"[OUT] {TRAIN_OUT}  （训练用，纯 messages）")

    # ── 泄漏复检 ──
    leak = [r for r in allrows
            if any(m["role"] == "user" and m["content"].strip() in ev
                   for m in r["messages"])]
    print(f"\n[泄漏复检] 与评测集原文重合：{len(leak)} 条 "
          f"{'✓ 干净' if not leak else '✗ 仍有泄漏'}")

    # ── 比例统计 ──
    def sys_of(r):
        for m in r["messages"]:
            if m["role"] == "system":
                return m["content"]
        return ""
    nor = [r for r in allrows if sys_of(r).startswith("模式：常规")]
    META = re.compile(r"(开关|露骨|授权|NSFW|非露骨|成人向)")
    ref = [r for r in nor if META.search(r["messages"][-1]["content"])]
    ok = [r for r in nor if not META.search(r["messages"][-1]["content"])]
    print(f"[比例] system=常规 {len(nor)} 条 → 拒写 {len(ref)} · 正常答 {len(ok)} "
          f"= 1 : {len(ok)/max(1,len(ref)):.2f}")
    print(f"       评测要求 1 : 1.20（正常答 25 : 拒写 30）")


if __name__ == "__main__":
    main()
