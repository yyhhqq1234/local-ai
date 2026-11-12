#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""labels 构造器 —— 绕开 chat_template 无 {% generation %} 的限制

背景（坑 A）：
  Qwen3.5 的 chat_template.jinja 只有 `add_generation_prompt`，**没有 {% generation %} 标记**，
  所以 trl 的 `SFTConfig(assistant_only_loss=True)` 无法定位 assistant 区间，
  要么报错、要么静默失效 —— 后果是 user/system 段也被算进 loss，
  模型会学着去"生成用户提问"，严重污染训练。

做法：
  用 apply_chat_template 分两次渲染：
    prompt_text = 模板(仅 system+user, add_generation_prompt=True)
    full_text   = 模板(全部消息, 含 assistant)
  full 的前 len(prompt_ids) 个 token 必然等于 prompt_ids（同一前缀）。
  labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids):]

  续段样本的 <carry_over> 落在 user 里 → 自动进 prompt 段 → 自动 -100。
  这正是我们要的：模型看到上文，但不对上文算 loss。

用法：
  # 自检（默认跑 3 条 kitty + 1 条轨迹 + 1 条切分续段）
  python label_builder.py --selftest

  # 给训练集做全量体检
  python label_builder.py --scan train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl --ctx 9216

  # 作为库使用
  from label_builder import build_labels
  ids, labels = build_labels(tok, messages)
"""

import argparse
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

IGNORE_INDEX = -100


def build_labels(tok, messages, add_eos=True):
    """返回 (input_ids, labels)

    messages: [{"role","content"}, ...]，最后一条通常是 assistant
    若没有 assistant，labels 全 -100（不可训练）
    """
    roles = [m.get("role") for m in messages]
    if "assistant" not in roles:
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        ids = tok(text, add_special_tokens=False).input_ids
        return ids, [IGNORE_INDEX] * len(ids)

    # 找到第一个 assistant 的位置，之前全部算 prompt
    cut = roles.index("assistant")
    prompt_msgs = messages[:cut]
    body_msgs = messages[cut:]

    if prompt_msgs:
        prompt_text = tok.apply_chat_template(
            prompt_msgs, tokenize=False, add_generation_prompt=True
        )
    else:
        prompt_text = ""

    full_text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)

    # 精确定位 assistant 正文的字符起点
    # 注意：Qwen3.5 模板在 add_generation_prompt=True 时会多插 "<think>\n"，
    #      而完整渲染（带 assistant 内容）不插 —— 所以不能直接用 len(prompt_text)，
    #      要用两者的最长公共前缀作为边界。
    if prompt_text and full_text.startswith(prompt_text):
        char_pos = len(prompt_text)
    elif prompt_text:
        k = 0
        m = min(len(prompt_text), len(full_text))
        while k < m and prompt_text[k] == full_text[k]:
            k += 1
        char_pos = k
    else:
        asst_probe = body_msgs[0].get("content", "")[:64]
        idx = full_text.find(asst_probe) if asst_probe else -1
        char_pos = idx if idx >= 0 else 0

    enc = tok(full_text, add_special_tokens=False, return_offsets_mapping=True)
    full_ids = enc["input_ids"]
    offs = enc["offset_mapping"]
    char_starts = [o[0] for o in offs]

    import bisect as _bisect

    prompt_len = _bisect.bisect_left(char_starts, char_pos) if char_pos > 0 else 0
    prompt_len = min(max(prompt_len, 0), len(full_ids))

    labels = [IGNORE_INDEX] * prompt_len + full_ids[prompt_len:]
    input_ids = full_ids

    if add_eos and not input_ids:
        pass
    return input_ids, labels


def report_one(tok, rec, verbose=False):
    """对单条样本做体检，返回 dict"""
    msgs = rec["messages"]
    ids, labels = build_labels(tok, msgs)
    n_sup = sum(1 for x in labels if x != IGNORE_INDEX)
    n_ign = len(labels) - n_sup

    first_sup = next((i for i, x in enumerate(labels) if x != IGNORE_INDEX), None)
    last_sup = next((i for i in range(len(labels) - 1, -1, -1) if labels[i] != IGNORE_INDEX), None)

    asst_decoded = tok.decode([t for t in labels if t != IGNORE_INDEX]) if n_sup else ""

    return {
        "total_tok": len(ids),
        "sup_tok": n_sup,
        "ign_tok": n_ign,
        "sup_ratio": round(n_sup / len(ids), 4) if ids else 0,
        "first_sup": first_sup,
        "last_sup": last_sup,
        "asst_preview": asst_decoded[:160].replace("\n", "⏎"),
        "asst_tail": asst_decoded[-120:].replace("\n", "⏎") if n_sup > 160 else "",
    }


def scan_file(tok, path, ctx, limit=None, show=0):
    total = 0
    bad_empty = 0
    bad_over = 0
    bad_all_ign = 0
    ratios = []
    with io.open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if not isinstance(rec.get("messages"), list):
                continue
            total += 1
            if limit and total > limit:
                break
            ids, labels = build_labels(tok, rec["messages"])
            n_sup = sum(1 for x in labels if x != IGNORE_INDEX)
            if n_sup == 0:
                bad_all_ign += 1
            if len(ids) > ctx:
                bad_over += 1
            if n_sup:
                ratios.append(n_sup / len(ids))
            if show and total <= show:
                r = report_one(tok, rec)
                print("  样本%d: %d tok, 可训练 %d (%.1f%%)" % (
                    total, r["total_tok"], r["sup_tok"], r["sup_ratio"] * 100))
                print("    assistant 首:", r["asst_preview"])
                if r["asst_tail"]:
                    print("    assistant 尾:", r["asst_tail"])

    ratios.sort()
    q = lambda x: ratios[min(int(len(ratios) * x), len(ratios) - 1)] if ratios else 0
    print("[%s]" % os.path.basename(path))
    print("  样本 %d 条" % total)
    print("  可训练 token 占比  p05=%.3f  p50=%.3f  p95=%.3f" % (q(0.05), q(0.5), q(0.95)))
    print("  label 全 -100 行 %d  |  超 ctx %d  |  空 assistant %d" % (bad_all_ign, bad_over, bad_empty))
    return {
        "file": path,
        "n": total,
        "ratio_p50": q(0.5),
        "all_ignore": bad_all_ign,
        "over_ctx": bad_over,
    }


def selftest(tok, ctx):
    print("=" * 60)
    print("SELFTEST 1: 普通单轮样本（kitty）")
    p = "train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl"
    rec = None
    with io.open(p, "r", encoding="utf-8") as f:
        rec = json.loads(f.readline())
    r = report_one(tok, rec)
    print("  total=%d  sup=%d  ign=%d  ratio=%.3f" % (
        r["total_tok"], r["sup_tok"], r["ign_tok"], r["sup_ratio"]))
    print("  首可训练位置 %d / 末 %d" % (r["first_sup"], r["last_sup"]))
    print("  assistant 首:", r["asst_preview"])
    assert r["sup_tok"] > 0, "ASSERT FAIL: assistant 段没有可训练 token"
    assert r["first_sup"] is not None and r["first_sup"] > 0, "ASSERT FAIL: 应从非 0 位置开始"

    print()
    print("=" * 60)
    print("SELFTEST 2: 切分续段（carry_over 必须在 -100 区间）")
    p2 = "train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-16k-chunk9216.jsonl"
    if os.path.exists(p2):
        with io.open(p2, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 找一条 chunk_idx>0 的
        rec2 = None
        for line in lines[:50]:
            o = json.loads(line)
            if (o.get("meta") or {}).get("chunk_idx", 0) > 0:
                rec2 = o
                break
        if rec2:
            r2 = report_one(tok, rec2)
            has_carry = "<carry_over>" in rec2["messages"][1]["content"]
            print("  含 carry_over: %s" % has_carry)
            print("  total=%d  sup=%d  ign=%d  ratio=%.3f" % (
                r2["total_tok"], r2["sup_tok"], r2["ign_tok"], r2["sup_ratio"]))
            print("  assistant 首:", r2["asst_preview"])
            # 验证：carry_over 文本不能出现在可训练 token 里
            carry_snippet = "carry_over"
            decoded_sup = tok.decode([t for t in tok(rec2["messages"][1]["content"]).input_ids])
            assert "<carry_over>" not in r2["asst_preview"], "ASSERT FAIL: carry 漏进了 labels"
            print("  ✓ carry_over 未进入可训练区间")
        else:
            print("  (跳过：没找到续段样本)")
    else:
        print("  (跳过：切分文件不存在)")

    print()
    print("=" * 60)
    print("SELFTEST 3: 全量扫描抽查")
    for p3 in [
        "train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl",
        "train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-8k.jsonl",
        "train/lines/_shared/data/nsfw/train-cont.jsonl",
    ]:
        if os.path.exists(p3):
            scan_file(tok, p3, ctx, limit=300)
            print()

    print("=" * 60)
    print("ALL SELFTEST PASSED")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--scan", default=None)
    ap.add_argument("--ctx", type=int, default=9216)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.tokenizer)

    if args.selftest:
        selftest(tok, args.ctx)
    elif args.scan:
        scan_file(tok, args.scan, args.ctx, args.limit, args.show)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
