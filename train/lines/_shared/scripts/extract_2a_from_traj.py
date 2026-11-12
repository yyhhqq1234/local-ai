#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
2A 数据重建 v2 —— 从【未切分的原始轨迹】提取，而不是从已污染的切片救

为什么重写（2026-10-30 08:00 发现）：
  第一版 rebuild_2a_data.py 从 traj-2a-v2.jsonl 救，产出 1399 条格式体检全 PASS，
  但抽查 user 发现 **99.3% 是 agent 执行日志碎片**：
    "<carry_over>\n[Command finished with exit code 0]\n[Current working directory: /workspace/...]"
  且 user 长度 P10=753 / P50=851 / P90=866 —— 固定的 850 字符切窗特征。
  这不是「用户提问」，是轨迹切片。模型学到的是「日志 -> 总结报告」，语义完全错位。
  **这才是 avg_cov 30.6% 的真正原因，比 B11/E20 更根本。**

本脚本改从原始未切分轨迹提取：
  train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-16k.jsonl   500 条（全部有 issue 描述，326 含代码块）
  train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-8k.jsonl   1500 条（全部有 issue 描述，972 含代码块）
  train/lines/9b-oxcoder/data/agent-traj/deepswe/deepswe-8k.jsonl     113 条（全部有 issue 描述， 29 含代码块）
  ⇒ 两者都有 1327 条可用

提取规则：
  user      : 取 <issue_description>...</issue_description>（没有则清理整段）
  assistant : 清 【assistant】/【observation】 标记 → 丢弃 observation 段和 [CALL xxx] 块
              → 取含代码块的段落 → 裁剪到 [min,max]，保证代码块闭合

用法：
  PYTHONIOENCODING=utf-8 train/.venv/Scripts/python.exe \
      train/lines/_shared/scripts/extract_2a_from_traj.py \
      --out train/lines/9b-oxcoder/data/agent-traj/traj-2a-v4.jsonl
"""
import argparse
import io
import json
import os
import re
import sys

BASE = "train/lines/9b-oxcoder/data/agent-traj"
DEFAULT_SRCS = [
    "nemotron-swe/swe-16k.jsonl",
    "nemotron-swe/swe-8k.jsonl",
    "deepswe/deepswe-8k.jsonl",
]

MARKS = (
    "【assistant】", "【user】", "【system】", "【observation】",
    "<|assistant|>", "<|user|>", "<|system|>",
    "### Assistant:", "### User:", "### System:",
)
SEG_RE = re.compile(r"(【assistant】|【observation】|<observation>|</observation>)")
# 只删 [CALL xxx] 所在行的工具调用（JSON 可能多行，但多行残留不影响代码块提取）
# 注意：不能用 r"\[CALL\s+\w+\]\s*\{.*" + re.S —— 贪婪会把后面所有内容删光
CALL_RE = re.compile(r"\[CALL\s+\w+\][^\n]*")
ISSUE_RE = re.compile(r"<issue_description>(.*?)</issue_description>", re.S)
FENCE_RE = re.compile(r"```.*?```", re.S)

SYSTEM_2A = (
    "You are a senior software engineer. When you are given a bug report or a code question, you:\n"
    "1. Identify the root cause precisely, naming the exact file, function and identifier involved.\n"
    "2. Give the concrete fix: show the code you would change, in a fenced code block.\n"
    "3. State how to verify the fix.\n"
    "Answer in the same language as the question. Do not ask for more information; reason from what is given."
)

# 问法增广（2026-10-30）：原始可用样本只有 667 条，训不动（667/4=167 步/epoch）。
# 同答案配不同问法，×3 扩到 2001 条。这是 SFT 常用手段，不改变答案语义。
AUG_PREFIXES = [
    "",
    "Please analyze this bug and provide the code fix:\n\n",
    "Diagnose the root cause and show the concrete code change:\n\n",
]


def strip_marks(s):
    for m in MARKS:
        s = s.replace(m, "")
    s = re.sub(r"[ \t]{2,}", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def extract_user(raw):
    """优先取 issue_description，其次清理整段。"""
    mo = ISSUE_RE.search(raw)
    if mo:
        txt = mo.group(1)
    else:
        txt = raw
        # 去掉 uploaded_files 之类的前缀块
        txt = re.sub(r"<uploaded_files>.*?</uploaded_files>", "", txt, flags=re.S)
        txt = re.sub(r"</?[a-z_]+>", "", txt)
    txt = strip_marks(txt)
    # 压掉过长的行内说明，保留 Title / Description
    txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
    return txt


def extract_assistant(raw):
    """
    按 【assistant】/【observation】 切段，只留 assistant 侧文本，
    丢弃 [CALL ...] 及其后面的 JSON 块，最后挑含代码块的部分。
    """
    parts = SEG_RE.split(raw)
    keep = []
    cur_is_asst = True       # 开头默认属于 assistant 侧
    for seg in parts:
        if seg == "【assistant】" or seg == "<observation>":
            cur_is_asst = True if seg == "【assistant】" else False
            continue
        if seg == "【observation】" or seg == "</observation>":
            cur_is_asst = False
            continue
        if cur_is_asst and seg:
            keep.append(seg)
    text = "\n".join(keep)
    # 丢弃工具调用块（[CALL xxx] 到段尾的 JSON）
    text = CALL_RE.sub("", text)
    text = strip_marks(text)
    if text.count("```") < 2:
        return None
    # 取最后一个含代码块的连续段（通常是最终修复总结）
    blocks = FENCE_RE.findall(text)
    if not blocks:
        return None
    last = blocks[-1]
    idx = text.rfind(last)
    start = max(0, idx - 1000)
    return text[start:]


def cut_at_boundary(s, limit, from_end=False):
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
    if text.count("```") % 2 != 0:
        text = text + "\n```"
    if len(text) <= hi and len(text) >= lo:
        return text
    blocks = FENCE_RE.findall(text)
    if not blocks:
        return None
    main = max(blocks, key=len)
    idx = text.find(main)
    if idx < 0:
        return None
    before_raw, after_raw = text[:idx], text[idx + len(main):]

    code_budget = int(hi * 0.55)
    if len(main) > code_budget:
        head = main[:code_budget]
        nl = head.rfind("\n")
        if nl > code_budget * 0.6:
            head = head[:nl]
        if head.count("```") % 2 == 1:
            head += "\n```"
        main = head

    remain = hi - len(main)
    before = cut_at_boundary(before_raw, int(remain * 0.6), from_end=True) if remain > 200 else ""
    after = cut_at_boundary(after_raw, int(remain * 0.4)) if remain > 200 else ""
    out = (before + ("\n\n" if before else "") + main +
           ("\n\n" + after if after else "")).strip()
    if out.count("```") % 2 != 0 or out.count("```") < 2:
        return None
    if len(out) < lo:
        return None
    return out[:hi]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--src", action="append", default=None,
                    help="可重复；默认用 nemotron-swe 的 16k/8k + deepswe-8k")
    ap.add_argument("--min-len", type=int, default=800, dest="min_len")
    ap.add_argument("--max-len", type=int, default=1500, dest="max_len")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    ap.add_argument("--aug", action="store_true",
                    help="问法增广 ×3（667 条太多不够训，扩到约 2001 条）")
    args = ap.parse_args()

    srcs = args.src or DEFAULT_SRCS
    n_in = n_out = 0
    drop_user = drop_fence = drop_trim = 0
    lens = []
    out_lines = []

    for rel in srcs:
        p = rel if os.path.isabs(rel) else os.path.join(BASE, rel)
        if not os.path.isfile(p):
            print("[skip] %s 不存在" % p)
            continue
        print("[read] %s" % p)
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            n_in += 1
            ms = d.get("messages") or []
            user_raw = asst_raw = ""
            for m in ms:
                if m.get("role") == "user":
                    user_raw += m.get("content", "")
                elif m.get("role") == "assistant":
                    asst_raw += m.get("content", "")
            if not user_raw or not asst_raw:
                drop_user += 1
                continue

            user = extract_user(user_raw)
            if len(user) < 80:
                drop_user += 1
                continue
            asst = extract_assistant(asst_raw)
            if asst is None:
                drop_fence += 1
                continue
            asst = trim_to_range(asst, args.min_len, args.max_len)
            if asst is None:
                drop_trim += 1
                continue

            meta = dict(d.get("meta") or {})
            meta["_src_file"] = rel
            prefixes = AUG_PREFIXES if args.aug else [""]
            for ai, pre in enumerate(prefixes):
                rec = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_2A},
                        {"role": "user", "content": pre + user},
                        {"role": "assistant", "content": asst},
                    ],
                    "meta": dict(meta, _aug_idx=ai),
                }
                out_lines.append(json.dumps(rec, ensure_ascii=False))
                lens.append(len(asst))
                n_out += 1

    if not n_out:
        sys.exit("[FATAL] 0 条通过，检查阈值")

    lens.sort()
    print()
    print("=" * 68)
    print("2A 数据重建 v2（从原始未切分轨迹）")
    print("=" * 68)
    print("输入          : %d 条" % n_in)
    print("丢弃-user不可用: %d" % drop_user)
    print("丢弃-无代码块 : %d" % drop_fence)
    print("丢弃-裁剪失败 : %d" % drop_trim)
    print("输出          : %d 条  (%.1f%%)" % (n_out, 100.0 * n_out / n_in))
    print("assistant 长度: P10=%d P50=%d P90=%d" % (
        lens[len(lens) // 10], lens[len(lens) // 2], lens[int(len(lens) * 0.9)]))
    print()

    if args.dry_run:
        print("[dry-run] 不写文件")
        return 0

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8") as f:
        for l in out_lines:
            f.write(l + "\n")
    print("[OK] 已写入 %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
