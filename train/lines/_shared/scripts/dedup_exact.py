"""精确去重 —— 同一 (user, assistant) 只留一条

轨迹切分会产出内容完全相同的片段（2026-10-28 实测 traj-all-capped 有 286 条 = 1.77%）。
它们不带来新信息，只会抬高记忆化，应去重。

注意：只去「完全相同」的，近重复（措辞不同）不动 —— 那是多样性，不是冗余。

用法：
  python dedup_exact.py --in <路径>                  # dry-run
  python dedup_exact.py --in <路径> --apply
  python dedup_exact.py --in <路径> --apply --out <新文件>
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", default=None, help="默认原地改（自动 .bak-dedup）")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.inp):
        sys.exit("[FATAL] 不存在: %s" % args.inp)

    seen = {}
    kept = []
    dropped = 0
    dup_groups = 0
    with io.open(args.inp, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            msgs = o.get("messages") or []
            u = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
            a = next((m.get("content", "") for m in msgs if m.get("role") == "assistant"), "")
            h = hashlib.md5((u + "\x00" + a).encode()).hexdigest()
            if h in seen:
                seen[h] += 1
                dropped += 1
            else:
                seen[h] = 1
                kept.append(line if line.endswith("\n") else line + "\n")

    dup_groups = sum(1 for v in seen.values() if v > 1)
    n_in = sum(seen.values())
    print("=" * 68)
    print("精确去重 —— %s" % args.inp)
    print("=" * 68)
    print("输入 %d 条 | 重复组 %d 个 | 将排除 %d 条 (%.2f%%)"
          % (n_in, dup_groups, dropped, dropped / n_in * 100 if n_in else 0))
    print("保留 %d 条" % len(kept))

    if not args.apply:
        print()
        print("[dry-run] 未写盘。加 --apply 生效。")
        return

    out = args.out or args.inp
    if out == args.inp:
        bak = args.inp + ".bak-dedup"
        if not os.path.exists(bak):
            shutil.copy2(args.inp, bak)
            print("备份 → %s" % bak)
    with io.open(out, "w", encoding="utf-8") as f:
        f.writelines(kept)
    print("[OK] 已写出 → %s（%d 条）" % (out, len(kept)))


if __name__ == "__main__":
    main()
