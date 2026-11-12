# -*- coding: utf-8 -*-
"""r3 验收对照器 —— 训练结束后一条命令出结论

背景：40 条泛化集口径（工具 + 参数 + 负向题），档3 基线：
    命中 10 / 参数错 21 / 选错 6 / 编造 1 / 回避 2  → acc 25.0%

r3 的四项验收目标（PLAN §5.1）：
    ① 参数错 21 → ≤8
    ② 命中 25% → ≥45%
    ③ 编造 保持 0
    ④ 负向题 N01–N04 保持 4/4

用法：
  # 1) 先跑评测（缓存带上，档3 秒回）
  python eval_multi_adapter.py --adapters "base=,tier3=train/lines/9b-oxcoder/out/re-stage1-r2/final,r3=train/lines/9b-oxcoder/out/re-stage1-r3/final" \\
      --max-new 300 --batch 1 --out train/lines/9b-oxcoder/out/eval-r3-40cases.json

  # 2) 再跑对照
  python compare_accept.py --eval train/lines/9b-oxcoder/out/eval-r3-40cases.json --new-label r3 --base-label tier3
"""
import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None


TARGETS = {
    "noarg_max": 8,      # 参数错 ≤8
    "acc_min": 0.45,     # 命中 ≥45%
    "fake_max": 0,       # 编造 0
    "neg_min": 4,        # 负向题 4/4
}
NEG_IDS = ["N01", "N02", "N03", "N04"]


def load(path):
    d = json.load(io.open(path, encoding="utf-8"))
    tiers = d.get("results") or []
    return tiers


def pick(tiers, label):
    for t in tiers:
        if t.get("label") == label:
            return t
    return None


def neg_pass(tier):
    """负向题通过数：expect 为空且 kind==hit"""
    ok = 0
    for d in tier.get("detail") or []:
        if d.get("id") in NEG_IDS and d.get("kind") == "hit":
            ok += 1
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True, help="eval_multi_adapter.py 的输出 JSON")
    ap.add_argument("--new-label", default="r3")
    ap.add_argument("--base-label", default="tier3")
    ap.add_argument("--out-md", default=None)
    args = ap.parse_args()

    tiers = load(args.eval)
    new = pick(tiers, args.new_label)
    base = pick(tiers, args.base_label)
    if not new:
        sys.exit("[FATAL] 找不到 label=%s，现有：%s"
                 % (args.new_label, [t.get("label") for t in tiers]))

    lines = []
    def say(s=""):
        print(s)
        lines.append(s)

    say("=" * 78)
    say("r3 验收对照 —— 40 条口径（工具 + 参数 + 负向）")
    say("=" * 78)
    say("eval: %s" % args.eval)
    say()

    cols = ["label", "n", "hit", "noarg", "wrong", "fake", "none", "acc", "L1/L2/L3"]
    say("%-10s %4s %5s %6s %6s %5s %5s %7s  %s" % tuple(cols))
    for t in tiers:
        lv = "/".join(str(t.get("by_level", {}).get(k, {}).get("hit", 0))
                      for k in ("L1", "L2", "L3"))
        say("%-10s %4d %5d %6d %6d %5d %5d %7.1f%%  %s"
            % (t.get("label", "?"), t.get("n", 0), t.get("hit", 0),
               t.get("noarg", 0), t.get("wrong", 0), t.get("fake", 0),
               t.get("none", 0), 100 * t.get("acc", 0), lv))
    say()

    # ── 四项验收 ────────────────────────────────────────────────
    noarg = new.get("noarg", 0)
    acc = new.get("acc", 0)
    fake = new.get("fake", 0)
    neg = neg_pass(new)
    checks = [
        ("参数错 ≤%d" % TARGETS["noarg_max"], noarg, "%d" % noarg, noarg <= TARGETS["noarg_max"]),
        ("命中 ≥%d%%" % int(TARGETS["acc_min"] * 100), acc, "%.1f%%" % (100 * acc), acc >= TARGETS["acc_min"]),
        ("编造 =%d" % TARGETS["fake_max"], fake, "%d" % fake, fake <= TARGETS["fake_max"]),
        ("负向 N01-N04 =%d/4" % TARGETS["neg_min"], neg, "%d/4" % neg, neg >= TARGETS["neg_min"]),
    ]
    say("── 四项验收 ──")
    say("%-22s %-10s %-12s %s" % ("项", "实测", "目标", "判定"))
    allpass = True
    for name, val, shown, ok in checks:
        say("%-22s %-10s %-12s %s" % (name, shown, name, "✅ PASS" if ok else "❌ FAIL"))
        if not ok:
            allpass = False
    say()

    # ── 逐条翻转 ────────────────────────────────────────────────
    if base:
        nd = {d["id"]: d for d in new.get("detail") or []}
        bd = {d["id"]: d for d in base.get("detail") or []}
        flips = []
        for i in sorted(set(nd) | set(bd)):
            kb, kn = bd.get(i, {}).get("kind"), nd.get(i, {}).get("kind")
            if kb != kn:
                flips.append((i, kb, kn, nd.get(i, {}).get("expect"),
                              nd.get(i, {}).get("missing")))
        say("── 逐条翻转（%s → %s）：%d 条 ──" % (args.base_label, args.new_label, len(flips)))
        if flips:
            say("%-5s %-7s → %-7s %-26s %s" % ("id", "旧", "新", "期望工具", "缺项"))
            for i, kb, kn, ex, miss in flips:
                arrow = "✅" if kn == "hit" else ("⚠" if kn == "noarg" else "")
                say("%-5s %-7s → %-7s %-26s %s %s"
                    % (i, kb, kn, ",".join(ex or [])[:24], miss or "", arrow))
        else:
            say("无变化")
        say()

        gained = sum(1 for _, kb, kn, _, _ in flips if kb != "hit" and kn == "hit")
        lost = sum(1 for _, kb, kn, _, _ in flips if kb == "hit" and kn != "hit")
        say("净翻转：+%d 变 hit / -%d 丢 hit" % (gained, lost))
        say()

    say("=" * 78)
    say("总判定：%s" % ("✅ 全部通过" if allpass else "❌ 未通过，见上表"))
    say("=" * 78)

    out = args.out_md
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        io.open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print("\n→ 报告落盘 %s" % out)
    sys.exit(0 if allpass else 1)


if __name__ == "__main__":
    main()
