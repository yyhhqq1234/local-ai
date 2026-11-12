#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""长样本按 token 预算切分 —— 零内容丢失版

问题：轨迹样本 assistant 段最长 13575 token，ctx 4096 时装不下，
      常规做法是「头 72% + 尾 28%」截断，中段全部丢弃。

本脚本改为：按自然边界切成多段，每段独立成 (system, user, assistant) 三元组。
- 切点优先级：工具调用步边界 "\n[CALL " > 空行 "\n\n" > 换行 "\n"
- 续段 user 里带上一段末尾 overlap token 作为上下文（context 进 user，
  训练时 assistant_only_loss 天然不计 loss，模型能看到但不背）
- 校验：所有段的非 overlap 字符拼接后必须等于原文（逐字节一致）

用法：
  # 只统计不写盘，看切分收益
  python chunk_train_samples.py --in f.jsonl --audit --ctx 4096

  # 实际切分
  python chunk_train_samples.py --in f.jsonl --out o.jsonl --ctx 4096

  # 批量处理一个目录
  python chunk_train_samples.py --in-dir train/lines/9b-oxcoder/data/agent-traj --out-dir train/data/chunked-4k --ctx 4096
"""

import argparse
import bisect
import glob
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

# 切点优先级：越靠前越优先（工具步边界 > 空行 > 换行）
SPLIT_PREFS = ("\n[CALL ", "\n\n", "\n")


def load_tok(model_dir):
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    if not tok.is_fast:
        raise SystemExit("需要 fast tokenizer 才能拿到 offsets")
    return tok


def ntok(tok, text):
    return len(tok.encode(text, add_special_tokens=False))


def find_cut(text, offsets, floor_tok, budget_tok):
    """在 token 区间 [floor_tok, budget_tok] 内从后往前找最佳字符切点。

    offsets: [(char_start, char_end), ...]，长度 = token 数
    返回字符下标 s，表示 text[:s] 为本段内容。
    """
    hi = min(budget_tok, len(offsets) - 1)
    lo = max(floor_tok, 1)
    if hi < lo:
        return None

    for pref in SPLIT_PREFS:
        plen = len(pref)
        for i in range(hi, lo - 1, -1):
            cs = offsets[i][0]
            if cs >= plen and text[cs - plen : cs] == pref:
                return cs
    # 兜底：硬切在 budget 位置的 token 起始处（保证不超 ctx）
    return offsets[hi][0]


def chunk_one(rec, tok, ctx, overlap_tok, carry_chars=None):
    """切分单条样本。返回 (段列表, 统计dict)"""
    msgs = rec.get("messages") or []
    sys_msgs = [m for m in msgs if m.get("role") == "system"]
    usr_msgs = [m for m in msgs if m.get("role") == "user"]
    asst_msgs = [m for m in msgs if m.get("role") == "assistant"]

    sys_tok = sum(ntok(tok, m["content"]) for m in sys_msgs)
    usr_tok = sum(ntok(tok, m["content"]) for m in usr_msgs)
    asst_text = "\n".join(m["content"] for m in asst_msgs)
    asst_tok = ntok(tok, asst_text)

    base = sys_tok + usr_tok + 64  # +64 覆盖 chat template 的角色标记 / <think> 等实际开销
    total = base + asst_tok

    stat = {
        "orig_tok": total,
        "orig_chars": len(asst_text),
        "sys_tok": sys_tok,
        "usr_tok": usr_tok,
        "asst_tok": asst_tok,
    }

    if total <= ctx:
        return [rec], dict(stat, chunks=1, split=False, covered_chars=len(asst_text))

    if not asst_msgs:
        return [rec], dict(stat, chunks=1, split=False, covered_chars=0, note="no-assistant")

    # 每段可用 assistant 预算
    # 预算不足 overlap 的两倍时，先把 overlap 压到 0 换预算（否则会切出大量碎片段）
    overlap_eff = overlap_tok if overlap_tok else 0
    budget = ctx - base - overlap_eff
    if budget < max(512, 2 * overlap_eff):
        overlap_eff = 0
        budget = ctx - base
    if budget < 128:
        # 提示词本身就占满窗口 —— 明确报错而不是静默截断
        return [rec], dict(
            stat,
            chunks=1,
            split=False,
            covered_chars=0,
            error="CTX_TOO_SMALL: base=%d ctx=%d 剩余预算=%d" % (base, ctx, budget),
        )

    enc = tok(asst_text, add_special_tokens=False, return_offsets_mapping=True)
    offsets = enc["offset_mapping"]
    char_starts = [o[0] for o in offsets]  # 单调递增，供二分

    segs = []
    start_tok = 0
    n = len(offsets)
    guard = 0
    while start_tok < n and guard < 20000:
        guard += 1
        cs = offsets[start_tok][0]
        end_tok = min(start_tok + budget, n)
        if end_tok >= n:
            cut = len(asst_text)
            cut_tok = n
        else:
            cut = find_cut(asst_text, offsets, start_tok + budget // 2, end_tok)
            if cut is None or cut <= cs:
                cut = offsets[end_tok][0]
            cut_tok = bisect.bisect_left(char_starts, cut)
            # 最小前进量：切点若离本段起点太近（无换行的长行文本），硬切到预算上限，
            # 否则会产生几十字符的碎片段，膨胀失控
            if cut_tok - start_tok < max(16, budget // 4):
                cut = offsets[end_tok][0]
                cut_tok = end_tok
            if cut_tok <= start_tok:
                cut_tok = end_tok
                cut = offsets[end_tok][0]
        segs.append((cs, cut))
        if cut >= len(asst_text):
            break
        # 下一段起点：从实际切点回退 overlap token（关键：用 cut_tok 不是 end_tok）
        nxt = cut_tok - overlap_eff
        if nxt <= start_tok:
            nxt = start_tok + 1
        start_tok = nxt

    out = []
    covered = 0
    for k, (cs, ce) in enumerate(segs):
        body = asst_text[cs:ce]
        covered += len(body)
        if k == 0:
            new_user = "\n\n".join(m["content"] for m in usr_msgs)
        else:
            carry = asst_text[max(0, cs - carry_chars) : cs]
            new_user = (
                "<carry_over>\n%s\n</carry_over>\n\n"
                "承接上文继续（第 %d/%d 段）。不要重复已写内容，从断点处直接往下写。"
                % (carry, k + 1, len(segs))
            )
        new_msgs = []
        for m in sys_msgs:
            new_msgs.append({"role": "system", "content": m["content"]})
        new_msgs.append({"role": "user", "content": new_user})
        new_msgs.append({"role": "assistant", "content": body})

        meta = dict(rec.get("meta") or {})
        meta.update(
            {
                "chunk_idx": k,
                "chunk_total": len(segs),
                "chunk_of_orig_tok": total,
                "chunk_char_start": cs,
                "chunk_char_end": ce,
            }
        )
        new_rec = {"messages": new_msgs, "meta": meta}
        if "id" in rec:
            new_rec["id"] = "%s#%d" % (rec["id"], k)
        out.append(new_rec)

    stat.update(
        {
            "chunks": len(segs),
            "split": True,
            "covered_chars": len(asst_text),  # 区间完整覆盖时 == 原文长度
            "overlap_chars": sum(max(0, segs[i][1] - segs[i + 1][0]) for i in range(len(segs) - 1)),
            "segs": segs,
            "carry_chars": sum(len(o["messages"][1]["content"]) for o in out[1:])
            if len(out) > 1
            else 0,
        }
    )
    return out, stat


def verify_lossless(orig_len, segs):
    """区间覆盖校验：必须从 0 起、到 orig_len 止、相邻无空洞（允许重叠）。

    返回 (ok, reason)
    """
    if not segs:
        return False, "empty"
    if segs[0][0] != 0:
        return False, "start=%d != 0" % segs[0][0]
    if segs[-1][1] != orig_len:
        return False, "end=%d != %d" % (segs[-1][1], orig_len)
    for i in range(len(segs) - 1):
        a, b = segs[i], segs[i + 1]
        if b[0] > a[1]:
            return False, "gap at seg%d: [%d,%d) -> [%d,%d)" % (i, a[0], a[1], b[0], b[1])
        if b[0] < a[0]:
            return False, "non-monotonic at seg%d" % i
        if b[1] <= a[1]:
            return False, "no-progress at seg%d" % i
    return True, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=None)
    ap.add_argument("--out", dest="out", default=None)
    ap.add_argument("--in-dir", default=None)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--ctx", type=int, default=4096)
    ap.add_argument("--overlap", type=int, default=256, help="续段带多少 token 上下文")
    ap.add_argument("--carry-chars", type=int, default=800, help="carry_over 文本字符数")
    ap.add_argument("--audit", action="store_true", help="只统计不写盘")
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    ap.add_argument("--report", default=None, help="统计 JSON 落盘路径")
    args = ap.parse_args()

    tok = load_tok(args.tokenizer)

    jobs = []
    if args.inp:
        jobs.append((args.inp, args.out))
    elif args.in_dir:
        for p in sorted(glob.glob(os.path.join(args.in_dir, "**", "*.jsonl"), recursive=True)):
            rel = os.path.relpath(p, args.in_dir)
            jobs.append((p, os.path.join(args.out_dir, rel) if args.out_dir else None))
    else:
        raise SystemExit("需要 --in 或 --in-dir")

    all_stat = []
    for src, dst in jobs:
        rows = []
        stats = []
        lossless_fail = 0
        errors = 0
        skipped = 0
        err_list = []
        with io.open(src, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if not isinstance(rec, dict) or not isinstance(rec.get("messages"), list):
                    skipped += 1
                    continue
                segs, st = chunk_one(rec, tok, args.ctx, args.overlap, args.carry_chars)
                if st.get("error"):
                    errors += 1
                    err_list.append(
                        {
                            "id": rec.get("id") or (rec.get("meta") or {}).get("__src"),
                            "err": st["error"],
                        }
                    )
                # 无损校验（区间覆盖）
                if st.get("split"):
                    asst_len = st["orig_chars"]
                    ok, why = verify_lossless(asst_len, st["segs"])
                    if not ok:
                        lossless_fail += 1
                        print("  [LOSSLESS-FAIL]", why, file=sys.stderr)
                rows.extend(segs)
                stats.append(st)

        n_in = len(stats)
        n_out = len(rows)
        tok_in = sum(s["orig_tok"] for s in stats)
        tok_out = 0
        chars_in = sum(s["orig_chars"] for s in stats)
        chars_out = sum(s["covered_chars"] for s in stats)
        n_split = sum(1 for s in stats if s.get("split"))
        overflow = 0
        max_out = 0
        for r in rows:
            t = sum(ntok(tok, m["content"]) for m in r["messages"]) + 12
            max_out = max(max_out, t)
            if t > args.ctx:
                overflow += 1
        tok_out = sum(
            sum(ntok(tok, m["content"]) for m in r["messages"]) + 12 for r in rows
        )

        rec_stat = {
            "file": src,
            "ctx": args.ctx,
            "overlap": args.overlap,
            "rows_in": n_in,
            "rows_out": n_out,
            "split_rows": n_split,
            "tok_in": tok_in,
            "tok_out": tok_out,
            "tok_ratio": round(tok_out / tok_in, 4) if tok_in else 0,
            "chars_in": chars_in,
            "chars_out": chars_out,
            "char_cover": round(chars_out / chars_in, 6) if chars_in else 1.0,
            "lossless_fail": lossless_fail,
            "overflow_rows": overflow,
            "max_row_tok": max_out,
            "errors": errors,
            "skipped_non_sample": skipped,
            "error_detail": err_list[:20],
        }
        all_stat.append(rec_stat)

        print(
            "[%s] ctx=%d  %d→%d 行  token %.2fM→%.2fM (×%.3f)  字符覆盖 %.6f  超ctx %d  无损失败 %d  跳过非样本 %d  错误 %d"
            % (
                os.path.basename(src),
                args.ctx,
                n_in,
                n_out,
                tok_in / 1e6,
                tok_out / 1e6,
                rec_stat["tok_ratio"],
                rec_stat["char_cover"],
                overflow,
                lossless_fail,
                skipped,
                errors,
            )
        )

        if not args.audit and dst:
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            with io.open(dst, "w", encoding="utf-8") as fo:
                for r in rows:
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            print("    → %s" % dst)

    if args.report:
        os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
        with io.open(args.report, "w", encoding="utf-8") as fo:
            json.dump(all_stat, fo, ensure_ascii=False, indent=2)
        print("report → %s" % args.report)


if __name__ == "__main__":
    main()
