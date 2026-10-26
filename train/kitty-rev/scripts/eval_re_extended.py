#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval_re_extended.py -- judge the 60-question reverse set with `meta.expect` rules.

Why a separate judge
    `eval_kitty.py` dispatches on `meta.cat` through a fixed RULES table; it has
    no rule-driven mode, so a new category cannot be added without editing it.
    This script is a thin wrapper: it REUSES eval_kitty's HTTP client, tool
    schema and call/text extraction, and adds an `expect`-driven judge so the
    60 items stay data (not code).

Expect grammar (all optional, all case-insensitive substrings unless noted)
    required        list[str]   every string must appear
    required_any    list[str]   at least one must appear
    forbidden       list[str]   none may appear
    regex_required  list[regex] every regex must match
    regex_any       list[regex] at least one must match
    order           list[list]  first hit of each group must increase
    min_chars       int         minimum answer length
    min_kitty       int         minimum distinct kitty tools + OP tokens

Both the answer text AND any tool_call `op`/`action` argument are searched, so
an OP question passes whether the model emits the OP inline or as a tool call.

Self-test (no model, no GPU)
    python eval_re_extended.py --selftest      # 6 hand-written answers, 4 good 2 bad
    Expected: SELFTEST 6/6

Usage
    python eval_re_extended.py --base http://127.0.0.1:18000 --model base-qwen3.8-27b \
        --out logs/eval-re-extended.json
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time

# GBK 控制台自保：本文件的输出里有 ≥ / ✓ 之类的非 GBK 字符。在没设
# PYTHONIOENCODING 的 Windows 控制台直接 `python xxx.py --selftest` 会抛
# UnicodeEncodeError —— 看上去像"自检崩了"，其实是编码（#14 的同族复发）。
# 这里把 stdout/stderr 钉成 utf-8，调用者不需要记得设环境变量。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # 非 TextIOWrapper（被重定向/被包裹）时跳过
    pass

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../kitty-rev
OP_TOKENS = ("S_NEW|S_SNAP|S_CHANGED|S_UNCHANGED|S_GET|S_FREE|P_BACK|P_BACK_RES|P_WALK|"
             "MODENUM|MODBASE|R|W|LP|CUR|PING|ALLOC|FREE|MEMDUMP_HEX|VER|BATCH|"
             "DBG_ATTACH|DBG_BP|DBG_GO|DBG_REGS|DBG_WAIT|DBG_STAT|KM_ATTACH|KM_R|KM_W|"
             "KM_PA|KM_PR|SYNC_ARCHIVE|SYNC_STAT")
OP_RE = re.compile(r"\b(" + OP_TOKENS + r")\b")
# Models answer with "ghidra" / "x64dbg" far more often than "kitty_ghidra".
# Counting only the prefixed form made two good answers fail -- so bare tool
# names count too, and `min_kitty` means "names a concrete instrument".
BARE_TOOLS = re.compile(
    r"\b(ghidra|ida|x64dbg|windbg|objdump|die|sym|dump|patch|prot|inject|asm|"
    r"engines|rea|drv|km|ce|ops|settings|status|sym)\b", re.I)

# forbidden 命中的否定豁免：正确答案常写「不要原样重试」「别再无脑 attach」，
# 纯子串匹配会把这类句子当成犯规（实测 3/3 误杀）。
NEG_CUES = ("不要", "不必", "不用", "别", "勿", "不能", "不可", "避免", "禁止",
            "无需", "不再", "不需要", "不该", "不是")


def tool_count(blob):
    low = blob.lower()
    return len(set(re.findall(r"kitty_[a-z_]+", low))
               | set(m.lower() for m in BARE_TOOLS.findall(blob))
               | set(m.upper() for m in OP_RE.findall(blob.upper())))


def load_eval_kitty():
    p = os.path.join(HERE, "eval", "eval_kitty.py")
    if not os.path.exists(p):
        raise SystemExit(f"[FATAL] 找不到 {p}")
    spec = importlib.util.spec_from_file_location("eval_kitty_re", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def judge(row, text, calls):
    """Return (ok, why). `text` and any tool_call args are both searched."""
    exp = (row.get("meta") or {}).get("expect") or {}
    ops = []
    for c in calls or []:
        a = c.get("args") or {}
        v = a.get("op") or a.get("action") or a.get("taskTransition") or ""
        if isinstance(v, str) and v:
            ops.append(v)
    blob = (text or "") + "\n" + "\n".join(ops)
    low = blob.lower()
    why = []
    ok = True

    # ---- 匹配口径 --------------------------------------------------------
    # 三个曾经造成误判的口径问题，全部在这里收口：
    # 1) 子串匹配不看否定："不要重试，改用 filter 分次拉" 会命中 forbidden=重试
    #    → 正确答案被判失败（实测误杀）。
    # 2) 只在 text 上算 min_chars：模型把 OP 放进 tool_call、正文为空时，
    #    长度判定失败 → 正确答案被判失败（docstring 承诺两处都搜，但长度只看一处）。
    # 3) order 组里 size=ida 这类短 ASCII 词用纯子串找，"validate" 里也能命中。
    # alt_all 用于给同一道题的第二条合格路径（例如自然语言版 OP），
    # 只有在"没有踩 forbidden、且 alt 全部命中"时才翻盘。
    def _negated(idx, span=12):
        head = low[max(0, idx - span):idx]
        return any(c in head for c in NEG_CUES)

    def _find(key):
        """第一次未被否定的出现位置；找不到返回 -1。"""
        k = key.lower()
        if not k:
            return -1
        if k.isascii() and k.replace("_", "").isalnum():
            pat = re.compile(r"(?<![a-z0-9_])" + re.escape(k), re.I)
            for m in pat.finditer(low):
                if not _negated(m.start()):
                    return m.start()
            return -1
        start = 0
        while True:
            i = low.find(k, start)
            if i < 0:
                return -1
            if not _negated(i):
                return i
            start = i + 1

    forbidden_hit = []
    for s in exp.get("forbidden", []):
        if _find(s) >= 0:
            forbidden_hit.append(s)
    if forbidden_hit:
        ok = False
        why.append("出现禁止「" + "/".join(forbidden_hit[:2]) + "」")

    for s in exp.get("required", []):
        if _find(s) < 0:
            ok = False
            why.append(f"缺「{s}」")
    ra = exp.get("required_any", [])
    if ra and not any(_find(s) >= 0 for s in ra):
        ok = False
        why.append(f"未命中任一 {ra[:3]}")
    for rx in exp.get("regex_required", []):
        if not re.search(rx, blob, re.I):
            ok = False
            why.append(f"正则未匹配 {rx[:48]}")
    rxs = exp.get("regex_any", [])
    if rxs and not any(re.search(rx, blob, re.I) for rx in rxs):
        ok = False
        why.append("regex_any 全未命中")

    order = exp.get("order") or []
    if order:
        last = -1
        for grp in order:
            hits = [_find(k) for k in grp]
            hits = [h for h in hits if h >= 0]
            if not hits:
                ok = False
                why.append(f"顺序组缺 {grp[:2]}")
                break
            first = min(hits)
            if first <= last:
                ok = False
                why.append(f"顺序错乱 {grp[:2]}")
                break
            last = first

    mc = exp.get("min_chars")
    if mc and len(blob.strip()) < mc:
        # measure the SEARCHED text, not just the prose: an OP emitted as a
        # tool call has an empty `text` and would fail a length gate it satisfies
        ok = False
        why.append(f"太短 {len(blob.strip())}<{mc}")

    mk = exp.get("min_kitty")
    if mk:
        n = tool_count(blob)
        if n < mk:
            ok = False
            why.append(f"工具/OP 计数 {n}<{mk}")

    alt = exp.get("alt_all") or []
    if alt and not ok and not forbidden_hit:
        # Second acceptable path (e.g. the same OP written as prose). The hit
        # positions must INCREASE: `0xSTOP ... 0xSTART` (range written backwards)
        # still contains both addresses, so a set-based check would call a wrong
        # OP correct. Ordered check == same information, same order.
        pos = [_find(s) if _find(s) >= 0 else low.find(s.lower()) for s in alt]
        if all(p >= 0 for p in pos) and all(a < b for a, b in zip(pos, pos[1:])):
            ok = True
            why = [w for w in why if not w.startswith(("regex", "未命中", "太短"))]
            why.append("alt_all 按序命中（等价表述）")
    return ok, "; ".join(why) if why else "ok"


# --------------------------------------------------------------------------- #
# self-test: 6 hand-written answers (4 good, 2 bad), no model needed
# --------------------------------------------------------------------------- #
SELFTEST = [
    (0, "PE 正例",
     "用 kitty_dump 按节表转储该镜像，再核对镜像头与导入解析结果；"
     "因为 .text 熵 6.71 且无 .pdata，静态展开不可靠，需要从内存里拿真实节内容。",
     True),
    (15, "OP 正例（4 段显式区间）",
     "S_NEW|dword|1500|0x7FF700000000|0x7FF750000000",
     True),
    (30, "决策链正例（triage→static→dynamic）",
     "第一步先做 triage：看形态、熵、导入，判断是否加壳；"
     "第二步做静态分析，用 ghidra 反编译关键函数并看 xref；"
     "第三步动态跑起来，用 x64dbg 下断点验证真实行为与参数。",
     True),
    (45, "错误恢复正例（换等价动作）",
     "把扫描窗口收紧到 0x7FF700000000-0x7FF710000000 并分段扫描，"
     "先用小窗口收敛候选，避免一次 200 命中上限被截断。",
     True),
    (15, "OP 反例（无区间，应 FAIL）",
     "S_NEW|dword|1500",
     False),
    (45, "错误恢复反例（原样重试，应 FAIL）",
     "再跑一次同样的 P_BACK，这次应该能过。",
     False),
]


def run_selftest(data_path):
    rows = [json.loads(l) for l in open(data_path, encoding="utf-8")]
    print(f"=== selftest（{len(SELFTEST)} 条人工答案，不加载模型、不联网）===")
    good = 0
    for idx, label, text, expect_pass in SELFTEST:
        row = rows[idx]
        calls = []
        # an OP answer may also arrive as a tool call; exercise that path once
        if row["meta"]["cat"] == "re-op-syntax" and expect_pass:
            calls = [{"name": "kitty_ce", "args": {"op": text}}]
        ok, why = judge(row, text, calls)
        hit = (ok == expect_pass)
        good += hit
        print(f"[{idx:02d}] {label:32s} 期望={'PASS' if expect_pass else 'FAIL'} "
              f"实判={'PASS' if ok else 'FAIL'}  {'✓' if hit else '✗'}  {why}")
    print(f"SELFTEST {good}/{len(SELFTEST)}")
    return 0 if good == len(SELFTEST) else 1


def main():
    ap = argparse.ArgumentParser(description="judge the 60-question reverse evaluation set")
    ap.add_argument("--base", default="http://127.0.0.1:18000")
    ap.add_argument("--model", default="base-qwen3.8-27b")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "eval_re_extended.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--out", default="")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return run_selftest(a.data)

    ek = load_eval_kitty()
    rows = [json.loads(l) for l in open(a.data, encoding="utf-8")]
    if a.limit:
        rows = rows[:a.limit]
    print(f"[eval] {len(rows)} 题  base={a.base} model={a.model} "
          f"judge=expect-rules data={os.path.basename(a.data)}")

    results, t0 = [], time.time()
    for i, row in enumerate(rows, 1):
        meta = row.get("meta") or {}
        user = row["messages"][0]["content"]
        try:
            resp = ek.post(a.base, a.model,
                           [{"role": "system", "content": ek.SYS},
                            {"role": "user", "content": user}],
                           max_tokens=a.max_tokens)
            txt, calls = ek.text_of(resp), ek.calls_of(resp)
        except Exception as e:
            results.append({"i": i, "cat": meta.get("cat"), "topic": meta.get("topic"),
                            "pass": False, "why": f"request failed: {e}"})
            print(f"[{i}/{len(rows)}] {meta.get('cat'):22s} FAIL (request error: {e})")
            continue
        ok, why = judge(row, txt, calls)
        results.append({"i": i, "cat": meta.get("cat"), "topic": meta.get("topic"),
                        "pass": bool(ok), "why": why, "calls": len(calls), "chars": len(txt)})
        print(f"[{i}/{len(rows)}] {meta.get('cat'):22s} {'PASS' if ok else 'FAIL'}  {why}")
        if a.verbose and not ok:
            print("    text: " + (txt or "")[:260].replace("\n", " "))

    n = len(results)
    p = sum(1 for r in results if r["pass"])
    by_cat = {}
    for r in results:
        c = r["cat"] or "?"
        by_cat.setdefault(c, [0, 0])
        by_cat[c][1] += 1
        by_cat[c][0] += 1 if r["pass"] else 0
    print("\n" + "=" * 64)
    print(f"总通过 {p}/{n} = {p / max(1, n) * 100:.1f}%   用时 {time.time() - t0:.0f}s")
    for c, (ok, tot) in sorted(by_cat.items(), key=lambda x: -x[1][1]):
        print(f"  {c:24s} {ok}/{tot}")
    thr = 8
    print(f"信号门槛：+{thr}/60 = 13.3%（≈p<0.05 粗略阈）；"
          f"当前距门槛 {thr - p if p < thr else 0} 题")
    print("=" * 64)

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"suite": "re_extended", "model": a.model, "base": a.base,
                       "pass": p, "total": n, "signal_threshold": thr,
                       "byCat": {c: {"pass": v[0], "total": v[1]} for c, v in by_cat.items()},
                       "detail": results}, f, ensure_ascii=False, indent=2)
        print(f"[ok] 报告 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
