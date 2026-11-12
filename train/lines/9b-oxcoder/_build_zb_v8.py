#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Z-B v8 构建：把 6 组混淆工具里「没有工具调用」的样本，重配成「场景 + 同工具真实调用」

━━ 依据（2026-11-02 18:20 实测）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
v4 mix 7608 条里只有 45% 输出工具调用（<tool_call> 11.1% + 裸调用 33.9%），
55% 是参数说明 / 工具描述 / 其他说明 —— 教的是「介绍工具」而不是「用工具」。

6 组混淆工具内部更差：1865 条里 966 条（52%）没有调用，其中
  ce_vs_prot        62% 无调用  ← v4 的 G13 就错在这组
  dualview_pchain   64% 无调用  ← v4 的 G09 参数错也在这组

━━ 做法（不编造、不加行）━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
对 966 条无调用样本：
  ① user 侧一个字不动（保留原场景/原问法）
  ② assistant 换成「同一工具」的**真实调用样本**（从 899 条有调用样本里借）
  ③ 借用时按 action 关键词匹配：user 提到 top 就优先借带 top 的那条
  ④ 借不到同工具的，跳过不改（宁可不动，不编造）
总行数保持 7608。

输出：data/_legacy/mix-z-re-v8.jsonl  +  _v8_report.json
"""
import io, json, os, re, random, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "data", "_legacy", "mix-z-re-v4.jsonl")
OUT = os.path.join(HERE, "data", "_legacy", "mix-z-re-v8.jsonl")
REPORT = os.path.join(HERE, "data", "_legacy", "_v8_report.json")

GROUPS = {
    "init_vs_drv":     ["kitty_init", "kitty_drv"],
    "ida_vs_ghidra":   ["kitty_ida", "kitty_ghidra"],
    "settings_vs_g3":  ["kitty_settings", "reverse_add_target", "reverse_add_obs"],
    "trail_vs_g3":     ["kitty_trail"],
    "ce_vs_prot":      ["kitty_ce", "kitty_prot"],
    "dualview_pchain": ["kitty_dualview", "kitty_pchain"],
}
ALL_TOOLS = set(t for v in GROUPS.values() for t in v)

TOOL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\b")
CALL_RE = re.compile(r"\b(kitty_[a-z_]+|reverse_[a-z_]+)\s+action=([\w\-]+)")
TC_RE = re.compile(r"<tool_call>")
# 常见 action / 参数关键词（用于匹配借用）
KEYWORDS = ["init", "status", "ensure", "recover", "host", "analyze", "functions",
            "xrefs", "decompile", "search", "target-set", "target-get", "host-rebind",
            "append", "get", "op", "batch", "query", "protect", "rwx", "dualview",
            "pchain", "top", "timeout", "addr", "samples", "depth", "out"]


def getu(r):
    for m in r["messages"]:
        if m["role"] == "user":
            return m["content"]
    return ""


def geta(r):
    return r["messages"][-1]["content"]


def primary_tool(text):
    t = TOOL_RE.findall(text)
    return t[0] if t else None


def has_call(a):
    return bool(CALL_RE.search(a) or TC_RE.search(a))


def kwset(text):
    low = text.lower()
    return {k for k in KEYWORDS if k in low}


def main():
    random.seed(20251106)
    rows = [json.loads(l) for l in io.open(SRC, encoding="utf-8") if l.strip()]
    print(f"[IN] v4 mix {len(rows)} 行")

    # ① 建索引：工具 → 有调用样本列表
    pool = collections.defaultdict(list)
    for r in rows:
        a = geta(r)
        if not has_call(a):
            continue
        t = primary_tool(a)
        if t:
            pool[t].append(a)

    print("[IDX] 各工具有调用样本数：")
    for t in sorted(ALL_TOOLS):
        if pool.get(t):
            print(f"   {t:<20}{len(pool[t])}")

    # ② 逐条处理 6 组内的无调用样本
    changed, skipped, by_group = 0, 0, collections.Counter()
    for r in rows:
        a = geta(r)
        u = getu(r)
        t = primary_tool(a)
        if not t or t not in ALL_TOOLS:
            continue
        in_group = any(t in ms for ms in GROUPS.values())
        if not in_group or has_call(a):
            continue
        cands = pool.get(t)
        if not cands:
            skipped += 1
            continue
        # 按 user 里的关键词挑最匹配的 assistant
        ukw = kwset(u)
        best, best_score = None, -1
        for c in random.sample(cands, min(40, len(cands))):
            score = len(ukw & kwset(c))
            if score > best_score:
                best, best_score = c, score
        if best is None:
            skipped += 1
            continue
        r["messages"][-1]["content"] = best
        changed += 1
        by_group[t] += 1

    print(f"\n[改] 重配 assistant：{changed} 条 · 跳过 {skipped} 条（无同工具可用样本）")
    print("   按工具分布：", dict(by_group.most_common()))

    # ③ 校验：总行数不变 + 每条仍有 user/assistant
    assert len(rows) == 7608, f"行数变了：{len(rows)}"
    bad = [i for i, r in enumerate(rows)
           if not getu(r).strip() or not geta(r).strip()]
    assert not bad, f"有 {len(bad)} 条缺 user/assistant"

    # ④ 前/后形态对比
    before = 3421
    after = sum(1 for r in rows if has_call(geta(r)))
    print(f"\n[形态] 有工具调用的样本：{before} ({before/7608*100:.1f}%) → {after} ({after/7608*100:.1f}%)")

    # ⑤ 定稿清洗 + 输出
    io.open(OUT, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    io.open(REPORT, "w", encoding="utf-8").write(json.dumps({
        "src": os.path.basename(SRC), "out": os.path.basename(OUT),
        "rows": len(rows), "rewired": changed, "skipped": skipped,
        "call_before": before, "call_after": after,
        "by_tool": dict(by_group),
    }, ensure_ascii=False, indent=1))
    print(f"\n[OUT] {OUT}")
    print(f"[OUT] {REPORT}")


if __name__ == "__main__":
    main()
