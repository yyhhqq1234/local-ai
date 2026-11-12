#!/usr/bin/env python
"""analyze_re_dataset.py — 逆向训练集质量诊断（只读，不改数据）

用法:
  python train/lines/_shared/scripts/analyze_re_dataset.py --data train/lines/9b-oxcoder/data/_legacy/mix-re.jsonl
  python train/lines/_shared/scripts/analyze_re_dataset.py --data train/lines/27b-kittyrev/data/versions/mix-re.20261027-011850.jsonl --ref

维度:
  1 基础统计   条数 / 字符 / 轮数分布
  2 重复      精确重复 + 3-gram Jaccard 近似重复（阈值 0.8）
  3 拒绝话术  assistant 里出现「我不能/无法协助/I cannot…」→ 会反向强化拒绝行为
  4 工具覆盖   kitty_* 等工具名出现频次与分布（决定模型能否真的调工具）
  5 领域覆盖   PE / 固件 / 移动 / 游戏内存 / 网络协议 / SDK 关键词
  6 指令模板化 user 前 12 字的高频前缀（模板化严重会限制泛化）
  7 长度异常  过短（<80 字）与过长（>6000 字）
"""
import argparse
import collections
import json
import re
import sys

REFUSAL_PAT = re.compile(
    r"(我不能|无法协助|不能提供|抱歉[，,]?\s*我|不允许|I cannot|I can't|I'm unable|I am unable|"
    r"I won't|I will not|无法帮助|不便提供)", re.I)

TOOLS = ["kitty_ce", "kitty_km", "kitty_dbg", "kitty_x64dbg", "kitty_patch", "kitty_asm",
         "kitty_dump", "kitty_sym", "kitty_ghidra", "kitty_ida", "kitty_pchain", "kitty_acescan",
         "kitty_prot", "kitty_inject", "kitty_dualview", "kitty_wpb", "kitty_ops", "kitty_status",
         "S_NEW", "P_BACK", "P_WALK", "MODENUM", "MEMDUMP_HEX", "km_read", "km_write"]

DOMAINS = {
    "PE/ELF": ["PE ", "PE头", ".text", "节表", "IAT", "ELF", "入口点", "RVA", "重定位"],
    "固件": ["固件", "firmware", "squashfs", "uboot", "JTAG", "UART", "binwalk"],
    "移动": ["APK", "smali", "Frida", "Xposed", "JNI", "dex", "AArch64"],
    "游戏内存": ["血量", "指针链", "基址", "实体列表", "视角", "内存扫描", "偏移"],
    "网络协议": ["抓包", "pcap", "帧", "握手", "重放", "TCP", "UDP"],
    "SDK/引擎": ["il2cpp", "Unity", "Unreal", "UE4", "Mono"],
    "加壳/反调试": ["加壳", "脱壳", "anti-debug", "反调试", "OLLVM", "VMP", "混淆"],
    "许可/授权": ["license", "许可", "注册机", "卡密", "激活", "校验"],
}

NGRAM = 3


def ngrams(text: str, n=NGRAM):
    t = re.sub(r"\s+", "", text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--near-dup-threshold", type=float, default=0.8)
    ap.add_argument("--top-near-dup", type=int, default=6)
    a = ap.parse_args()

    rows = []
    with open(a.data, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[BAD JSON] line {ln}: {e}")

    n = len(rows)
    print(f"=== {a.data} ===")
    print(f"样本数 {n}")

    # ── 1 基础统计 ────────────────────────────────
    u_lens, a_lens, turns = [], [], []
    empty_assist = 0
    for r in rows:
        msgs = r.get("messages") or []
        turns.append(len(msgs))
        u = " ".join(m["content"] for m in msgs if m.get("role") == "user")
        ass = " ".join(m["content"] for m in msgs if m.get("role") == "assistant")
        u_lens.append(len(u))
        a_lens.append(len(ass))
        if not ass.strip():
            empty_assist += 1

    def stat(name, xs):
        xs = sorted(xs)
        if not xs:
            return
        p = lambda q: xs[min(len(xs) - 1, int(len(xs) * q))]
        print(f"{name:12} min {xs[0]:6}  p25 {p(.25):6}  med {p(.5):6}  "
              f"p75 {p(.75):6}  p95 {p(.95):6}  max {xs[-1]:6}  mean {sum(xs)//len(xs):6}")

    stat("user 字符", u_lens)
    stat("assistant 字符", a_lens)
    stat("轮数", turns)
    if empty_assist:
        print(f"[!] assistant 为空的样本: {empty_assist}")

    # 长度异常
    short = [i for i, x in enumerate(a_lens) if x < 80]
    long_ = [i for i, x in enumerate(a_lens) if x > 6000]
    print(f"[i] assistant <80 字符: {len(short)} 条   >6000 字符: {len(long_)} 条")

    # ── 2 重复 ────────────────────────────────────
    full = ["\x00".join(m.get("content", "") for m in (r.get("messages") or [])) for r in rows]
    exact = n - len(set(full))
    print(f"\n=== 重复 ===")
    print(f"精确重复 {exact} 条")

    grams = [ngrams(x) for x in full]
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            gi, gj = grams[i], grams[j]
            if not gi or not gj:
                continue
            inter = len(gi & gj)
            if inter / max(len(gi | gj), 1) >= a.near_dup_threshold:
                pairs.append((round(inter / len(gi | gj), 3), i, j))
    pairs.sort(reverse=True)
    print(f"近似重复(3-gram Jaccard ≥ {a.near_dup_threshold}) {len(pairs)} 对")
    for s, i, j in pairs[:a.top_near_dup]:
        print(f"  {s}  #{i} vs #{j}  | {(full[i][:40])!r}")

    # ── 3 拒绝话术 ────────────────────────────────
    refuse_rows = []
    for i, r in enumerate(rows):
        ass = " ".join(m.get("content", "") for m in (r.get("messages") or [])
                       if m.get("role") == "assistant")
        m = REFUSAL_PAT.search(ass)
        if m:
            refuse_rows.append((i, m.group(0)))
    print(f"\n=== 拒绝话术（会反向强化拒绝行为）===")
    print(f"命中 {len(refuse_rows)} / {n} 条 ({len(refuse_rows)/max(n,1):.1%})")
    for i, kw in refuse_rows[:8]:
        print(f"  #{i}  {kw!r}")

    # ── 4 工具覆盖 ────────────────────────────────
    blob = "\n".join(full)
    print(f"\n=== 工具覆盖 ===")
    hit = [(t, blob.count(t)) for t in TOOLS]
    hit.sort(key=lambda x: -x[1])
    zero = [t for t, c in hit if c == 0]
    print("  频次前列: " + ", ".join(f"{t}={c}" for t, c in hit[:8] if c))
    if zero:
        print(f"  未出现({len(zero)}): {', '.join(zero)}")

    # ── 5 领域覆盖 ────────────────────────────────
    print(f"\n=== 领域覆盖 ===")
    for dom, kws in DOMAINS.items():
        c = sum(blob.count(k) for k in kws)
        cnt_rows = sum(1 for x in full if any(k in x for k in kws))
        bar = "█" * min(20, cnt_rows // max(1, n // 20)) if cnt_rows else ""
        print(f"  {dom:10} 关键词 {c:5} 次   涉及 {cnt_rows:4} 条 ({cnt_rows/max(n,1):5.1%})  {bar}")

    # ── 6 指令模板化 ──────────────────────────────
    print(f"\n=== user 前 12 字高频前缀 ===")
    pref = collections.Counter()
    for r in rows:
        for m in (r.get("messages") or []):
            if m.get("role") == "user":
                pref[m.get("content", "")[:12]] += 1
                break
    for p, c in pref.most_common(8):
        if c > 1:
            print(f"  {c:4}  {p!r}")
    dup_prefix = sum(c for _, c in pref.most_common() if c > 1)
    print(f"  前缀重复覆盖 {dup_prefix}/{n} 条 ({dup_prefix/max(n,1):.1%})")

    print("\n=== 结论提示 ===")
    flags = []
    if len(refuse_rows) / max(n, 1) > 0.02:
        flags.append(f"拒绝话术占 {len(refuse_rows)/n:.1%}，SFT 会强化拒绝 —— 建议改写或剔除")
    if exact > 0 or len(pairs) > n * 0.05:
        flags.append("重复偏高，会放大过拟合")
    if dup_prefix / max(n, 1) > 0.3:
        flags.append("user 指令模板化严重，泛化受限")
    if zero:
        flags.append(f"{len(zero)} 个工具在数据中从未出现，模型不会用它们")
    weak = [d for d, kws in DOMAINS.items()
            if sum(1 for x in full if any(k in x for k in kws)) < n * 0.05]
    if weak:
        flags.append(f"领域偏弱(<5%): {', '.join(weak)}")
    if not flags:
        flags.append("未见硬伤")
    for f_ in flags:
        print(f"  · {f_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
