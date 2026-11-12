"""限制单条轨迹的片段数 —— 治「少数轨迹被过度切分、重复曝光」

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-10-28 实测发现
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
traj-all.jsonl 17553 条，按「user 前 120 字」归并出 12975 个原始任务，看似平均 1.4 片/任务。
但分布极度长尾：

    片段数 545  ← pandas-dev__pandas__1.0
    片段数 297  ← numpy__numpy__1.0
    片段数 217  ← 某条 carry_over 超长轨迹
    片段数 207  ← python-pillow__Pillow__1.0
    片段数 102  ← tornadoweb__tornado__1.0
    ...
    （前 5 大就占 1368 片段 = 7.8%）

每片的 user 都不同（原始任务描述 + 不同的 carry_over 上下文），所以不是重复行，
但**同一条 pandas issue 会被训练 545 次** → 模型把这 545 片全记住，严重加剧记忆化。
RE 阶段已实测「2 遍数据就把 4/10 条背到 n-gram 重合 1.00」，2A 这种 545 倍曝光必须治。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
做法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
按「user 前 120 字」分组 → 每组若超过 --max-per-task，**均匀采样**保留（保留时间轴分布，
不集中在前段）→ 被排除的写入 quarantine 文件（原数据不动）。

均匀采样用 floor 步长而非随机，保证可复现、且覆盖整条轨迹的各个阶段。

用法：
  python cap_traj_fragments.py                                # dry-run
  python cap_traj_fragments.py --apply --max-per-task 20
  python cap_traj_fragments.py --apply --max-per-task 20 --out <新文件>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import collections
import hashlib
import io
import json
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(TRAIN_ROOT, "data", "agent-traj", "traj-all.jsonl")
KEY_LEN = 120


def task_key(o):
    msgs = o.get("messages") or []
    u = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
    return hashlib.md5((u[:KEY_LEN] or "").encode()).hexdigest()


def uniform_pick(n, cap):
    """从 n 个里均匀取 cap 个下标（含首尾，步长 floor）"""
    if n <= cap:
        return list(range(n))
    idx = [int(i * n / cap) for i in range(cap)]
    return sorted(set(idx))[:cap]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=DEFAULT_IN)
    ap.add_argument("--out", default=None, help="默认原地改（自动 .bak-cap）")
    ap.add_argument("--max-per-task", type=int, default=20, dest="cap")
    ap.add_argument("--quarantine", default="", dest="q",
                    help="被排除的片段写入此文件")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.inp):
        sys.exit("[FATAL] 输入不存在: %s" % args.inp)

    # 第一遍：分组，记下每组的行号顺序
    groups = collections.defaultdict(list)
    rows = []
    with io.open(args.inp, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            rows.append((line, o))
            groups[task_key(o)].append(len(rows) - 1)

    n = len(rows)
    keep = set()
    dropped = 0
    affected = 0
    for k, idxs in groups.items():
        if len(idxs) <= args.cap:
            keep.update(idxs)
            continue
        affected += 1
        picked = uniform_pick(len(idxs), args.cap)
        keep.update(idxs[i] for i in picked)
        dropped += len(idxs) - len(picked)

    print("=" * 74)
    print("单任务片段数上限 = %d" % args.cap)
    print("=" * 74)
    print("输入片段 %d | 原始任务 %d 个" % (n, len(groups)))
    print("超限任务 %d 个 → 排除片段 %d 条（%.2f%%）"
          % (affected, dropped, dropped / n * 100 if n else 0))
    print("保留 %d 条（%.2f%%）" % (len(keep), len(keep) / n * 100 if n else 0))

    # 展示改动最大的 5 个任务
    top = sorted(((len(v), k) for k, v in groups.items()), reverse=True)[:5]
    print()
    print("改动最大的 5 个任务：")
    for cnt, k in top:
        if cnt <= args.cap:
            continue
        sample = rows[groups[k][0]][1]
        u = next((m.get("content", "") for m in sample["messages"] if m.get("role") == "user"), "")
        print("  %4d 片 → 保留 %d 片 | %s" % (cnt, args.cap, u[:70].replace("\n", " ")))

    if not args.apply:
        print()
        print("[dry-run] 未写盘。加 --apply 生效。")
        return

    out = args.out or args.inp
    if out == args.inp:
        bak = args.inp + ".bak-cap"
        if not os.path.exists(bak):
            shutil.copy2(args.inp, bak)
            print()
            print("备份 → %s" % bak)

    if args.q:
        os.makedirs(os.path.dirname(os.path.abspath(args.q)), exist_ok=True)
        with io.open(args.q, "w", encoding="utf-8") as qf:
            for i, (line, o) in enumerate(rows):
                if i in keep:
                    continue
                msgs = o.get("messages") or []
                u = next((m.get("content", "") for m in msgs if m.get("role") == "user"), "")
                qf.write(json.dumps({
                    "reason": "task_fragment_over_cap",
                    "task_size": len(groups[task_key(o)]),
                    "cap": args.cap,
                    "user_head": u[:200],
                }, ensure_ascii=False) + "\n")
        print("隔离清单 → %s（%d 条，原数据未删）" % (args.q, dropped))

    with io.open(out, "w", encoding="utf-8") as f:
        for i, (line, o) in enumerate(rows):
            if i in keep:
                f.write(line if line.endswith("\n") else line + "\n")
    print("[OK] 已写出 → %s（%d 条）" % (out, len(keep)))


if __name__ == "__main__":
    main()
