"""修正训练集里的工具名错字（不删任何内容，只改错名）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-10-28 全量扫描 train-kitty-core.jsonl 发现 4 处错名，tools.json 里不存在：
  · kitty_c        → kitty_ce          （line 2168 user）
  · kitty_ace      → kitty_acescan     （line 2571 user）
  · kitty_adb      → adb               （line 1230 / 3223 assistant；
                                        adb 是外部命令，不是 kitty 工具）
错名会教模型学出真幻觉，必须修。**只替换这 4 处，其余内容零改动。**

用法：
  python fix_typo_toolnames.py                    # dry-run，只报告
  python fix_typo_toolnames.py --apply            # 原地改（先自动备份 .bak）
  python fix_typo_toolnames.py --apply --out <新文件>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import io
import json
import os
import re
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(TRAIN_ROOT, "data", "kitty-reverse", "train-kitty-core.jsonl")
CONTRACT = os.path.join(TRAIN_ROOT, "data", "kitty-reverse", "kitty-contracts", "tools.json")

# 错名 → 正确写法。键用词边界正则，避免误伤 kitty_ce / kitty_acescan 本身
FIXES = [
    (r"\bkitty_c\b", "kitty_ce", "kitty_c 是 kitty_ce 的错拼"),
    (r"\bkitty_ace\b", "kitty_acescan", "kitty_ace 是 kitty_acescan 的错拼"),
    (r"\bkitty_adb\b", "adb", "adb 是外部命令，不是 kitty 工具"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=DEFAULT_IN)
    ap.add_argument("--out", default=None, help="输出路径（默认原地改）")
    ap.add_argument("--apply", action="store_true", help="真的写盘（默认 dry-run）")
    args = ap.parse_args()

    tools = {t["name"] for t in json.load(open(CONTRACT, encoding="utf-8"))}

    # 先自检：错名确实不在白名单，正确名确实在
    for pat, repl, why in FIXES:
        bad = re.sub(r"\\b", "", pat)
        assert bad not in tools, "%s 竟在白名单里，规则有误" % bad
        assert repl in tools or repl == "adb", "%s 不在白名单，规则有误" % repl

    totals = {pat: 0 for pat, _, _ in FIXES}
    lines_hit = set()
    out_lines = []

    with io.open(args.inp, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                out_lines.append(line)
                continue
            orig = line
            cur = line
            for pat, repl, _ in FIXES:
                new, n = re.subn(pat, repl, cur)
                if n:
                    totals[pat] += n
                    lines_hit.add(i)
                    cur = new
            out_lines.append(cur)

    print("=" * 72)
    print("工具名错字修正报告")
    print("=" * 72)
    print("输入：%s" % args.inp)
    for pat, repl, why in FIXES:
        print("  %-14s → %-16s 命中 %d 处   (%s)"
              % (re.sub(r"\\b", "", pat), repl, totals[pat], why))
    print("受影响行数：%d" % len(lines_hit))
    print()

    # 修完再扫一遍，确认零残留
    after = {}
    for line in out_lines:
        if not line.strip():
            continue
        o = json.loads(line)
        for m in o["messages"]:
            for t in set(re.findall(r"(?:kitty|reverse)_[a-z0-9_]+", m["content"])):
                if t in tools:
                    continue
                pref = [k for k in tools if t.startswith(k)]
                if pref:
                    continue
                after[t] = after.get(t, 0) + 1
    print("修正后仍非白名单的 token：%s"
          % (", ".join("%s×%d" % (k, v) for k, v in after.items()) or "无"))
    print()

    if not args.apply:
        print("[dry-run] 未写盘。加 --apply 生效。")
        return

    out = args.out or args.inp
    if out == args.inp:
        bak = args.inp + ".bak-typo"
        if not os.path.exists(bak):
            shutil.copy2(args.inp, bak)
            print("备份 → %s" % bak)
        else:
            print("备份已存在，不覆盖 → %s" % bak)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as f:
        f.writelines(out_lines)
    print("[OK] 已写出 → %s（%d 行）" % (out, len([x for x in out_lines if x.strip()])))


if __name__ == "__main__":
    main()
