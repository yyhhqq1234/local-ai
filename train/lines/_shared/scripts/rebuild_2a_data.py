#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
2A 训练数据重建 —— 修 B11 + E20

背景（2026-10-30 2A 训练失败复盘）：
  B11  66.3% 样本含【assistant】角色标记 -> 模型学会复读它，输出变成
       【assistant】【assistant】... 无限循环，三项指标同时崩坏
  E20  88.8% 样本无代码块、P50 长度 2444 -> code_rate 训成 2.5%（判据要 80%）

本脚本做三件事：
  1) 清角色标记（硬要求：输出必须 0%）
  2) 只保留含完整代码块（``` >= 2 个）的样本
  3) 智能裁剪到目标长度：保留「问题描述 + 主代码块 + 关键解释」，保证代码块闭合

用法：
  PYTHONIOENCODING=utf-8 train/.venv/Scripts/python.exe \
      train/lines/_shared/scripts/rebuild_2a_data.py \
      --src train/lines/9b-oxcoder/data/agent-traj/traj-2a-v2.jsonl \
      --out train/lines/9b-oxcoder/data/agent-traj/traj-2a-v3-clean.jsonl

  加 --dry-run 只看统计不写文件。

输出格式：{"messages": [system, user, assistant], "meta": {...}} 与现有训练脚本一致。
"""
import argparse
import io
import json
import os
import re
import sys

# B11: 角色标记。assistant/user 正文里出现任何一个都是污染。
MARKS = (
    "【assistant】", "【user】", "【system】",
    "<|assistant|>", "<|user|>", "<|system|>",
    "### Assistant:", "### User:", "### System:",
    "ASSISTANT:", "USER:", "SYSTEM:",
)

FENCE_RE = re.compile(r"```.*?```", re.S)
WS_RE = re.compile(r"[ \t]{2,}")
NL_RE = re.compile(r"\n{3,}")


def strip_marks(s):
    """删除角色标记并规整空白。返回 (新文本, 删掉的标记数)。"""
    if not s:
        return s, 0
    cnt = 0
    for m in MARKS:
        c = s.count(m)
        if c:
            cnt += c
            s = s.replace(m, "")
    s = WS_RE.sub(" ", s)
    s = NL_RE.sub("\n\n", s)
    return s.strip(), cnt


def cut_at_boundary(s, limit, from_end=False):
    """在 limit 附近找自然边界（换行/句号/分号）切，避免切在词中间。"""
    if len(s) <= limit:
        return s
    if from_end:
        seg = s[-limit:]
        for ch in ("\n", "。", ". ", "；", "; "):
            i = seg.find(ch)
            if 0 <= i < limit // 3:
                return seg[i + len(ch):]
        return seg
    seg = s[:limit]
    for ch in ("\n", "。", ". ", "；", "; "):
        i = seg.rfind(ch)
        if i > limit * 2 // 3:
            return seg[:i + len(ch)]
    return seg


def trim_to_range(text, lo, hi):
    """
    把超长文本压到 hi 以内，保留信息密度最高的部分：
      问题描述（代码块前） + 主代码块（最长那个） + 关键解释（代码块后）
    返回裁剪后的文本；若裁剪后代码块不完整则返回 None。
    """
    if len(text) <= hi:
        return text if text.count("```") >= 2 else None

    blocks = FENCE_RE.findall(text)
    if not blocks:
        return None

    main = max(blocks, key=len)
    idx = text.find(main)
    if idx < 0:
        return None

    before_raw = text[:idx]
    after_raw = text[idx + len(main):]

    # 预算：主代码块最多占 hi 的 55%，其余给前后文
    code_budget = int(hi * 0.55)
    if len(main) > code_budget:
        # 截断代码块内容，但补回闭合围栏
        head = main[:code_budget]
        nl = head.rfind("\n")
        if nl > code_budget * 0.6:
            head = head[:nl]
        if head.count("```") % 2 == 1:
            head += "\n```"
        main = head

    remain = hi - len(main)
    before = cut_at_boundary(before_raw, int(remain * 0.62), from_end=True) if remain > 200 else ""
    after = cut_at_boundary(after_raw, int(remain * 0.38)) if remain > 200 else ""

    out = (before + ("\n\n" if before else "") + main +
           ("\n\n" + after if after else "")).strip()

    if out.count("```") % 2 != 0:
        return None
    if out.count("```") < 2:
        return None
    if len(out) < lo:
        return None
    return out[:hi]


def get_parts(obj):
    """取 (system, user, assistant) 文本。"""
    sys_t = user_t = asst_t = ""
    for m in (obj.get("messages") or []):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        ct = m.get("content")
        if isinstance(ct, list):
            ct = "".join(b.get("text", "") for b in ct if isinstance(b, dict))
        if not isinstance(ct, str):
            continue
        if role == "system":
            sys_t += ct
        elif role == "user":
            user_t += ct
        elif role == "assistant":
            asst_t += ct
    return sys_t, user_t, asst_t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-len", type=int, default=800, dest="min_len")
    ap.add_argument("--max-len", type=int, default=1500, dest="max_len")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    args = ap.parse_args()

    if not os.path.isfile(args.src):
        sys.exit("[FATAL] src not found: %s" % args.src)

    n_in = 0
    n_mark_fixed = 0
    mark_removed = 0
    n_no_fence = 0
    n_trim_fail = 0
    n_out = 0
    lens = []
    kept_meta_repos = {}

    out_lines = []
    for line in io.open(args.src, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        n_in += 1

        sys_t, user_t, asst_t = get_parts(obj)
        if not user_t.strip() or not asst_t.strip():
            n_no_fence += 1
            continue

        # 1) 清标记（三个字段都清）
        sys_t, c1 = strip_marks(sys_t)
        user_t, c2 = strip_marks(user_t)
        asst_t, c3 = strip_marks(asst_t)
        removed = c1 + c2 + c3
        if removed:
            n_mark_fixed += 1
            mark_removed += removed

        # 2) 必须含代码块
        if asst_t.count("```") < 2:
            n_no_fence += 1
            continue

        # 3) 裁剪
        trimmed = trim_to_range(asst_t, args.min_len, args.max_len)
        if trimmed is None:
            n_trim_fail += 1
            continue

        meta = obj.get("meta") or {}
        meta = dict(meta)
        meta["_rebuilt"] = {
            "src": os.path.basename(args.src),
            "marks_removed": removed,
            "len_before": len(asst_t),
            "len_after": len(trimmed),
        }
        rec = {
            "messages": [
                {"role": "system", "content": sys_t},
                {"role": "user", "content": user_t},
                {"role": "assistant", "content": trimmed},
            ],
            "meta": meta,
        }
        out_lines.append(json.dumps(rec, ensure_ascii=False))
        lens.append(len(trimmed))
        n_out += 1
        repo = meta.get("repo", "?")
        kept_meta_repos[repo] = kept_meta_repos.get(repo, 0) + 1

    if not n_out:
        sys.exit("[FATAL] no sample survived; check thresholds")

    lens.sort()
    print("=" * 68)
    print("2A 数据重建报告")
    print("=" * 68)
    print("输入          : %d 条" % n_in)
    print("清掉角色标记  : %d 条（共删 %d 个标记）" % (n_mark_fixed, mark_removed))
    print("丢弃-无代码块 : %d 条" % n_no_fence)
    print("丢弃-裁剪失败 : %d 条（代码块无法在不破坏的前提下压进 [%d,%d]）"
          % (n_trim_fail, args.min_len, args.max_len))
    print("输出          : %d 条  (%.1f%% 保留率)" % (n_out, 100.0 * n_out / n_in))
    print()
    print("长度: P10=%d  P50=%d  P90=%d  min=%d  max=%d"
          % (lens[len(lens) // 10], lens[len(lens) // 2],
             lens[int(len(lens) * 0.9)], lens[0], lens[-1]))
    in_range = sum(1 for x in lens if args.min_len <= x <= args.max_len)
    print("落在 [%d,%d]: %d (%.1f%%)" % (
        args.min_len, args.max_len, in_range, 100.0 * in_range / n_out))
    print()
    print("来源分布（按 repo，前 8）:")
    for repo, c in sorted(kept_meta_repos.items(), key=lambda x: -x[1])[:8]:
        print("  %-40s %d" % (repo, c))
    print()

    if args.dry_run:
        print("[dry-run] 不写文件")
        return 0

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        for l in out_lines:
            f.write(l + "\n")
    print("[OK] 已写入 %s" % args.out)
    print()
    print("下一步：跑格式体检确认 0%% 污染且代码块达标")
    print("  PYTHONIOENCODING=utf-8 train/.venv/Scripts/python.exe \\")
    print("      train/lines/_shared/scripts/check_format_dist.py --data %s \\" % args.out)
    print("      --need-code 0.95 --len-min %d --len-max %d" % (args.min_len, args.max_len))
    return 0


if __name__ == "__main__":
    sys.exit(main())
