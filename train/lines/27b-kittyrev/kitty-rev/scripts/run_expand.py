# -*- coding: utf-8 -*-
"""run_expand.py —— 统筹扩展：契约模板(silver) + 轨迹/反例(gold) + 真实轨迹 → 大数据集

用法:
  python scripts/run_expand.py                       # 全量生成
  python scripts/run_expand.py --dry-run             # 只统计
  python scripts/run_expand.py --variants 8          # 加大 silver 变体乘数
  python scripts/run_expand.py --eval-ratio 0.08     # 验收集比例

输出: data/large/{train,eval,dpo}.jsonl + manifest.json
（data/train.jsonl 等旧文件保留不动；训练脚本用 --data 指定）
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "scripts"))

import expand_dataset as E          # noqa: E402
import expand_gold as G             # noqa: E402

DATA = E.DATA
OUT = os.path.join(DATA, "large")


import re as _re

_CJK = _re.compile(r"[\u4e00-\u9fa5]")


def est_tokens(text):
    c = len(_CJK.findall(text))
    return int(c * 1.0 + (len(text) - c) * 0.27)


def shrink(row, max_tok=1500, tool_cap=200):
    """超长轨迹按「长的先砍」裁剪：工具回包优先，其次中间 assistant；仍超限则丢弃。"""
    msgs = row.get("messages") or []
    last = len(msgs) - 1
    for _ in range(120):
        if est_tokens("\n".join(str(m.get("content", "")) for m in msgs)) <= max_tok:
            return row
        cands = sorted(
            ((len(str(m.get("content", ""))), i) for i, m in enumerate(msgs)
             if i != last and i != 0 and m.get("role") in ("tool", "assistant")),
            reverse=True,
        )
        if not cands:
            return None
        ln, i = cands[0]
        if ln <= tool_cap:
            return None
        msgs[i]["content"] = str(msgs[i]["content"])[: max(tool_cap, ln // 2)] + "…[truncated]"
    return None


def jlines(p):
    if not os.path.isfile(p):
        return []
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


# ---- 交叉：OP ↔ 工具 ----
def gen_op_tool_map():
    rows = []
    for o in E.OPS:
        holders = [t["name"] for t in E.TOOLS if o["op"] in (t.get("ops") or [])]
        if not holders:
            continue
        rows.append(E.sft(
            f"要发 `{o['op']}` 这条 OP，该用哪个工具？",
            f"用 `{holders[0]}`（通道 {E.TOOL_BY_NAME[holders[0]]['channel']}）。\n"
            f"签名：`{o['sig']}`\n回包：{o['reply']}\n"
            f"同族可选：{'、'.join(holders[:4])}。直接调 kitty_ce 也能发（op=…），专用工具会多做一步编排与判据。",
            "op-tool-map", "silver", op=o["op"], tool=holders[0]))
    return rows


def gen_action_reverse():
    rows = []
    for t in E.TOOLS:
        for act in (t["actions"] or []):
            rows.append(E.sft(
                f"`{act}` 是哪个 kitty 工具的 action？",
                f"`{act}` 属于 `{t['name']}`（通道 {t['channel']}，职责：{t['description']}）。\n"
                f"该工具全部 action：{'/'.join(t['actions'])}。\n"
                f"调用形态：{t['name']} action={act}" + (f"，配套 OP：{'、'.join(t['ops'][:6])}" if t.get("ops") else ""),
                "action-reverse", "silver", tool=t["name"], action=act))
    return rows


def gen_op_guard():
    rows = []
    for o in E.OPS:
        sig = o["sig"]
        head = sig.split("|")[0]
        bad = f"`{o['op']}` 直接一句话就能跑，不用给参数。"
        good = f"不行。`{o['op']}` 的签名是 `{sig}`（首段 `{head}`），缺段会 ERR|unknown 或 need-range。按签名逐段给。"
        rows.append(E.sft(f"我这样用对吗：{bad}", good, "guard", "guard", op=o["op"]))
    return rows


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        msgs = r["messages"]
        key = (msgs[0]["content"][:240], msgs[-1]["content"][:240])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", type=int, default=6)
    ap.add_argument("--eval-ratio", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=20261020)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    seed_sft = jlines(os.path.join(DATA, "seed_sft.jsonl"))
    seed_dpo = jlines(os.path.join(DATA, "seed_dpo.jsonl"))
    real_sft = jlines(os.path.join(DATA, "real_sft.jsonl"))
    real_neg = jlines(os.path.join(DATA, "real_neg.jsonl"))
    real_kitty = jlines(os.path.join(DATA, "real_kitty.jsonl"))
    real_disc = jlines(os.path.join(DATA, "real_disc.jsonl"))
    kb_sft = jlines(os.path.join(DATA, "kb_sft.jsonl"))
    kb_dpo = jlines(os.path.join(DATA, "kb_dpo.jsonl"))

    for r in seed_sft:
        r.setdefault("meta", {})["tier"] = "gold"
    for r in real_sft:
        r.setdefault("meta", {})["tier"] = "gold"
        r["meta"].setdefault("cat", "real-trajectory")
    for r in real_kitty:
        r.setdefault("meta", {})["tier"] = "gold"
        r["meta"]["cat"] = "real-kitty"
    for r in real_disc:
        r.setdefault("meta", {})["tier"] = "silver"
        r["meta"]["cat"] = "real-discipline"

    blocks = {
        "op-syntax": E.gen_op(a.variants),
        "tool-action": E.gen_tool_action(a.variants),
        "tool-route": E.gen_route(a.variants),
        "transition-syntax": E.gen_transition(a.variants),
        "error-recovery": E.gen_err(a.variants),
        "op-tool-map": gen_op_tool_map(),
        "action-reverse": gen_action_reverse(),
        "guard(op)": gen_op_guard(),
        "guard": G.gen_guard(),
        "trajectory": G.gen_scen(),
        "trajectory-variants": G.gen_scen_variants(),
        "next-action": G.gen_next_action(),
        "error-trajectory": G.gen_error_inject(),
    }

    all_rows = list(seed_sft) + list(real_sft) + list(real_kitty) + list(real_disc) + list(kb_sft)
    for _, rows in blocks.items():
        all_rows += rows
    all_rows = dedupe(all_rows)

    kept, dropped = [], 0
    for r in all_rows:
        if est_tokens("\n".join(str(m.get("content", "")) for m in r["messages"])) > 1500:
            r2 = shrink(r)
            if r2 is None:
                dropped += 1
                continue
            kept.append(r2)
        else:
            kept.append(r)
    all_rows = kept
    print(f"[shrink] kept={len(all_rows)} dropped_too_long={dropped}")

    # 分组切分：同一 prompt 前缀的样本必须落在同一侧（防 eval 泄漏到 train）
    rnd = random.Random(a.seed)
    groups = {}
    for r in all_rows:
        g = r["messages"][0]["content"][:40]
        groups.setdefault(g, []).append(r)
    gkeys = list(groups)
    rnd.shuffle(gkeys)
    target_eval = int(len(all_rows) * a.eval_ratio)
    eval_rows, train_rows = [], []
    for g in gkeys:
        if len(eval_rows) < target_eval:
            eval_rows += groups[g]
        else:
            train_rows += groups[g]
    rnd.shuffle(train_rows)
    rnd.shuffle(eval_rows)

    dpo = G.gen_dpo(seed_dpo, real_neg) + list(kb_dpo)

    cats, tiers = {}, {}
    for r in all_rows:
        c = r["meta"].get("cat", "?")
        cats[c] = cats.get(c, 0) + 1
        t = r["meta"].get("tier", "?")
        tiers[t] = tiers.get(t, 0) + 1

    manifest = {
        "generatedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "bridge": E.OPS_DOC.get("bridge"),
        "contracts": {"tools": E.TOOLS_DOC["count"], "ops": E.OPS_DOC["count"],
                       "transitions": len(E.TYPES), "errCodes": len(E.ERRCODES)},
        "sources": {"seed_sft": len(seed_sft), "real_sft": len(real_sft),
                    "real_kitty": len(real_kitty), "real_disc": len(real_disc),
                    "kb_sft": len(kb_sft), "seed_dpo": len(seed_dpo),
                    "real_neg": len(real_neg), "kb_dpo": len(kb_dpo)},
        "sft_total": len(all_rows),
        "sft_train": len(train_rows),
        "sft_eval": len(eval_rows),
        "dpo": len(dpo),
        "by_cat": dict(sorted(cats.items(), key=lambda x: -x[1])),
        "by_tier": dict(sorted(tiers.items(), key=lambda x: -x[1])),
        "blocks": {k: len(v) for k, v in blocks.items()},
        "avg_assistant_chars": round(sum(len(r["messages"][-1]["content"]) for r in all_rows) / max(1, len(all_rows)), 1),
        "est_tokens": {
            "avg": round(sum(est_tokens("\n".join(m["content"] for m in r["messages"])) for r in all_rows) / max(1, len(all_rows))),
            "max": max((est_tokens("\n".join(m["content"] for m in r["messages"])) for r in all_rows), default=0),
        },
        "dropped_too_long": dropped,
        "varsants": a.variants,
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

    if a.dry_run:
        print("[dry-run] 未落盘")
        return

    os.makedirs(OUT, exist_ok=True)

    def dump(name, rows):
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump("train.jsonl", train_rows)
    dump("eval.jsonl", eval_rows)
    dump("dpo.jsonl", dpo)
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[ok] → {OUT}  train={len(train_rows)} eval={len(eval_rows)} dpo={len(dpo)}")


if __name__ == "__main__":
    main()
