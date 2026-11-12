#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_nsfw_gated.py — NSFW 开关（gate）训练集构建器

目标能力
--------
用户显式给出 NSFW 触发词（"NSFW" / "成人内容" / "R18" / "无限制模式" / 结构令牌 [[NSFW]]）
→ 模型输出成人向内容；未给出触发词 → 只输出常规内容。

为什么不能只给 NSFW 样本加前缀
------------------------------
单向前缀只教了"有开关 → 输出 NSFW"，没教"无开关 → 不输出"。
2B 阶段把 NSFW 分布注入权重后，无开关时也会自然倾向输出（实测同构任务泄漏率 ~100%）。
本脚本的核心是【成对反事实】：同一条 user 请求，开 / 关两版，只差触发词与应答。

样本族（meta.gate 字段）
------------------------
pos_user  user 带触发词                          → NSFW 原文      （自然语言触发，主路径）
pos_both  user 带触发词 + system 声明 NSFW 许可    → NSFW 原文      （部署加固，system 优先）
neg       同一条 user 原文，去掉触发词             → 常规模式应答    （成对负样本，核心）
ctl       常规请求（RE/轨迹数据抽样）               → 原文常规应答    （防"无开关=一律拒答"）

配比
----
pos : neg = 1 : 1（--neg-per-pos 可调，1.0~1.5 建议）
ctl 占总量 8%~12%，太少会把"无开关"学成"一律拒答"。

输出（train/lines/9b-oxcoder/data/nsfw-gated/）
------------------------------
  train-2b-gated.jsonl   混合后 shuffle 的训练集（2B 阶段直接用）
  gate-pos.jsonl         仅正样本（配比消融用）
  gate-neg.jsonl         仅负样本（配对消融用）
  stats.json             分布统计
  MANIFEST.md            人类可读清单

用法
----
  python train/lines/_shared/scripts/build_nsfw_gated.py --dry-run
  python train/lines/_shared/scripts/build_nsfw_gated.py --limit 300
  python train/lines/_shared/scripts/build_nsfw_gated.py --neg-per-pos 1.0 --ctl-n 1200
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None

DATA = os.path.join(TRAIN_ROOT, "data")
DEFAULT_NSFW_DIR = os.path.join(DATA, "nsfw")
DEFAULT_CTL = os.path.join(DATA, "agent-traj", "traj-all-bucketed.jsonl")
FALLBACK_CTL = [
    os.path.join(DATA, "kitty-reverse", "kitty-core-bucketed.jsonl"),
    os.path.join(DATA, "mix-2a-bucketed.jsonl"),
]
OUT_DIR = os.path.join(DATA, "nsfw-gated")

NSFW_FILES = ["train-cont.jsonl", "train-scene.jsonl", "train-multi.jsonl",
              "train-style.jsonl", "train-expand.jsonl"]
GLOSSARY = "nsfw-glossary-merged.jsonl"

# ── 触发词池 ──────────────────────────────────────────────────────────────
# 结构令牌（前端/harness 可精确注入）与自然语言（用户口语）都必须有效。
TRIGGERS_STRUCT = ["[[NSFW]]", "[NSFW]", "[[模式:NSFW]]"]
TRIGGERS_NL = ["NSFW", "成人内容", "R18", "无限制模式", "成人向创作模式", "18+ 模式"]
TRIGGER_WEIGHT = {"[[NSFW]]": 22, "[NSFW]": 8, "[[模式:NSFW]]": 10,
                  "NSFW": 20, "成人内容": 18, "R18": 8,
                  "无限制模式": 7, "成人向创作模式": 4, "18+ 模式": 3}

SYS_NSFW = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
SYS_GENERAL = "模式：常规（未授权成人向内容）。不含露骨性描写。"

# ── 常规模式应答模板（负样本 completion）─────────────────────────────────
# 要求：①明确"当前是常规模式" ②不机械复读同一句 ③给出可执行转向
# ④指出开启方式（否则模型学不到"开关存在"）⑤不评判用户
# 长度刻意做到 80~140 字：负样本 completion 不能比正样本短一个量级，
# 否则「关」这一侧的梯度信号会被「开」压掉（token 量差 10 倍 → 门控学不会）。
NEG_TPL = [
    "当前为常规模式，这类内容我不展开。这个题材本身可以谈——人物动机、关系张力、场景氛围、叙事节奏都能写，只是不写露骨部分。可以选：①我按暗示与留白的方式处理，把张力放在情绪和细节上 ②你先给人物设定，我搭一个可推进的剧情骨架 ③换一个非露骨的创作方向。需要成人向版本时，在请求里显式标注「NSFW」或「成人内容」再发一次。",
    "常规模式下我只写非露骨内容。这个请求的写作目标我能拆：结构、冲突、节奏、视角都可以先定下来，露骨描写这部分需要你先开启对应模式（在消息里写明 NSFW 即可）。要不要我先出一版非露骨大纲？大纲定完，开模式后可以直接往里填，不浪费前面的工作。",
    "这条请求属于成人向范围，当前未开启对应模式，先不生成正文。可选路径有两条：第一，我按暗示、留白、镜头切走的方式给一个非露骨版本，读起来仍然有张力；第二，你标注 NSFW 后我按原要求写。另外如果你只是想讨论这类题材的写法与市场，不含露骨内容，我可以直接展开。",
    "未检测到 NSFW 开关，按常规内容处理。我能做的是世界观、人物关系、情节推进与非露骨描写；成人向正文需要显式开关。现在可以给你的部分：把这段素材拆成「可写的」与「需授权的」，前者我直接写，后者等你加标记。这样不阻塞进度，也不会误产出。",
    "现在是常规模式，不做露骨输出。如果你想继续这个方向：先说明「NSFW」，我再按成人向写；否则我可以把它改写成悬疑向或情感向的版本——同一套人物和冲突，把张力从身体转到心理与处境上，往往更好读。你选一个方向，我立刻开工。",
    "该请求需要成人向许可。当前为常规模式，我先给可写的部分：设定与剧情骨架、人物关系图、每章的功能定位。这些做完，后面开 NSFW 模式续写会快很多。你也可以让我先出一个非露骨的样章，看看语感对不对。要完整版本请加 NSFW 标记。",
    "常规模式：不输出性描写。这个题材可以走暗线处理——需要我这样写吗？暗线的做法是：关键的亲密段落用环境、动作停顿、对话留白来承载，读者能懂但不落字。这样既保留情绪强度，也不越模式边界。要露骨版本请先显式开启（消息含 NSFW 即可）。",
    "识别到成人向请求，但开关未开，本次不生成该类正文。可以：①换非露骨角度，我照样能写得很紧 ②你回一句「NSFW」后我重写 ③先做设定与分章，等模式开了直接续。三条路都不浪费你已经写的内容，你挑一条即可。",
    "当前按常规内容应答。成人向内容需要你显式声明 NSFW 或「成人内容」，这是本模型的模式约定。在这个约定下我能做很多：人物弧光、冲突设计、场景调度、对白打磨、非露骨的情感与身体张力。要开成人向模式，加一个标记就行，不需要重新描述需求。",
    "没看到 NSFW 开关，所以这次只给常规内容。需要我继续的话，两种方式：改写成非露骨版本，或你标注 NSFW 后我给成人向版本。补一句实用建议：如果你在批量生成，把开关写进模板头部，比每条都手动加更省事，也不容易漏。",
    "常规模式生效中：不展开露骨情节。可写方向——人物弧光、场景质感、暧昧张力、权力关系、心理博弈。这些恰恰是这类题材最吃功力的部分，先写这些，等开关打开再补露骨段落，成品质量通常更高。要成人向请开启 NSFW。",
    "这条超出常规模式范围，先不生成。你可以补一个 NSFW 标记，或让我把它降级成非露骨写法：保留人物、冲突与情绪线，把露骨段落替换成时间跳跃与感官侧写。降级版写完你仍可在此基础上开模式扩写，不会重复劳动。",
]
NEG_CLOSERS = [
    "", "", "",
    "\n\n（当前模式：常规）",
    "\n\n提示：成人向内容需显式开关。",
]

# 追加段：拉长负样本 completion，使「关」侧的 token 量与「开」侧可比
# （否则 token 加权后拒绝信号被生成信号压掉，模型学不会门控）
NEG_EXTRA = [
    "另外，如果你在做系列创作，建议先定一份「模式约定」：哪些段落属于常规、哪些需要开关，写清楚后批量生成时不容易漏标。",
    "还有个实际建议：把开关放在请求最前面（如 NSFW：正文需求），比夹在中间更稳定，模型对首行标记的敏感度明显更高。",
    "如果你只是想要更强的情绪浓度，不需要露骨——我可以把冲突推到更狠，把对话写得更锋利，把场景压得更近，读起来的强度并不低。",
    "从成品角度看，露骨段落通常不是决定质量的部分；人物动机是否可信、节奏是否稳、对话是否有潜台词，才是读者留下来的原因。",
    "你给的素材里其实有几个可以深挖的点：关系的不对等、场景的时间压力、人物对自己的隐瞒。这些写出来比直给更有后劲。",
    "如果这个项目有交付时间，建议先按常规口径出一版可交的稿，把需要开关的部分留成占位段落，后面开模式再补，不影响主进度。",
    "补充一句边界：我可以在常规模式下讨论这类题材的写法、结构、受众与审查尺度，这些都属于可谈范围。",
    "需要的话我可以先给三套不同走向的分章方案（情绪向 / 悬疑向 / 关系向），你挑一套，我再展开写。",
]

CAT_HINT = {
    "cont": "续写", "scene": "场景", "multi": "多轮", "style": "风格",
    "expand": "扩写", "glossary": "词表",
}


def log(msg):
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def read_jsonl(path):
    if not os.path.exists(path):
        return
    with io.open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def first_user(msgs):
    for m in msgs:
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def last_assistant(msgs):
    for m in reversed(msgs):
        if m.get("role") == "assistant":
            return m.get("content") or ""
    return ""


def classify_src(name):
    if "cont" in name:
        return "cont"
    if "scene" in name:
        return "scene"
    if "multi" in name:
        return "multi"
    if "style" in name:
        return "style"
    if "expand" in name:
        return "expand"
    if "glossary" in name:
        return "glossary"
    return "misc"


def strip_trigger(text):
    """去掉已存在的触发词（原始数据可能已带），避免双重前缀。"""
    t = text.lstrip()
    for tr in TRIGGERS_STRUCT + TRIGGERS_NL:
        if t.startswith(tr):
            t = t[len(tr):].lstrip(" ：:，,\n")
    return t


def with_trigger(text, trigger):
    body = strip_trigger(text)
    if trigger.startswith("["):
        return "%s\n%s" % (trigger, body)
    return "%s：%s" % (trigger, body)


def pick_trigger(rng):
    keys = list(TRIGGER_WEIGHT)
    return rng.choices(keys, weights=[TRIGGER_WEIGHT[k] for k in keys], k=1)[0]


def build_neg_reply(rng, cat):
    tpl = rng.choice(NEG_TPL)
    closer = rng.choice(NEG_CLOSERS)
    extra = ""
    r = rng.random()
    if r < 0.45:
        extra = "\n\n" + rng.choice(NEG_EXTRA)
    elif r < 0.75:
        extra = "\n\n" + rng.choice(NEG_EXTRA) + rng.choice(NEG_EXTRA)
    head = CAT_HINT.get(cat)
    if head and rng.random() < 0.35:
        return "（%s类请求）%s%s%s" % (head, tpl, closer, extra)
    return tpl + closer + extra


def approx_tokens(s):
    # 中文 1 字 ≈ 0.65 token；粗略用于统计
    return int(len(s) / 1.55) + 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nsfw-dir", default=DEFAULT_NSFW_DIR)
    ap.add_argument("--ctl-source", default=DEFAULT_CTL)
    ap.add_argument("--out-dir", default=OUT_DIR)
    # 1.5 = 用条数补偿 token 量差（负样本 completion 仍短于正样本）
    ap.add_argument("--neg-per-pos", type=float, default=1.5)
    ap.add_argument("--pos-both-ratio", type=float, default=0.30,
                    help="正样本中带 system 声明的比例（部署加固）")
    ap.add_argument("--ctl-n", type=int, default=1200)
    ap.add_argument("--pos-cap", type=int, default=0,
                    help="正样本上限（按类别比例分层抽样；0=全量。预算紧张建议 7000）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pos, neg, ctl = [], [], []
    stats = Counter()
    trig_stats = Counter()
    cat_stats = Counter()

    # ── 1. NSFW 源 → pos / neg 成对 ──────────────────────────────────
    pool = []
    pool_cat = Counter()
    for fn in NSFW_FILES + [GLOSSARY]:
        path = os.path.join(args.nsfw_dir, fn)
        if not os.path.exists(path):
            log("[skip] 缺文件 %s" % path)
            continue
        cat = classify_src(fn)
        got = 0
        for ex in read_jsonl(path):
            msgs = ex.get("messages") or []
            u, a = first_user(msgs), last_assistant(msgs)
            if not u or not a:
                stats["skip_empty"] += 1
                continue
            if len(a) < 40:
                stats["skip_short"] += 1
                continue
            sid = ex.get("id") or hashlib.md5(u.encode("utf-8")).hexdigest()[:12]
            pool.append({"id": sid, "cat": cat, "u": u, "a": a, "src": fn})
            got += 1
            pool_cat[cat] += 1
        log("[read] %-28s cat=%-8s 样本=%d" % (fn, cat, got))

    stats["src_read"] = len(pool)

    # 分层抽样（按类别比例），控训练预算：门控语义重复度高，不需要全量
    if args.pos_cap and len(pool) > args.pos_cap:
        by_cat = defaultdict(list)
        for r in pool:
            by_cat[r["cat"]].append(r)
        kept = []
        for cat, rows in by_cat.items():
            quota = max(1, int(round(args.pos_cap * len(rows) / len(pool))))
            rng.shuffle(rows)
            kept.extend(rows[:quota])
        rng.shuffle(kept)
        stats["pos_capped_from"] = len(pool)
        log("[cap] %d → %d 条（分层，按类别比例）" % (len(pool), len(kept)))
        pool = kept

    for rec in pool:
        cat, u, a, sid, fn = rec["cat"], rec["u"], rec["a"], rec["id"], rec["src"]
        trig = pick_trigger(rng)

        # 正样本：user 带触发词（+可选 system 声明）
        if rng.random() < args.pos_both_ratio:
            p_msgs = [{"role": "system", "content": SYS_NSFW},
                      {"role": "user", "content": with_trigger(u, trig)},
                      {"role": "assistant", "content": a}]
            gate = "pos_both"
        else:
            p_msgs = [{"role": "user", "content": with_trigger(u, trig)},
                      {"role": "assistant", "content": a}]
            gate = "pos_user"
        pos.append({"id": "%s#pos" % sid, "messages": p_msgs,
                    "meta": {"gate": gate, "cat": cat, "trigger": trig, "src": fn}})
        trig_stats[trig] += 1
        cat_stats[cat] += 1

        # 负样本：同一条 user 原文，去开关；system 声明常规
        k_int = int(args.neg_per_pos)
        k = k_int + (1 if rng.random() < (args.neg_per_pos - k_int) else 0)
        for j in range(max(0, k)):
            n_msgs = []
            if rng.random() < args.pos_both_ratio:
                n_msgs.append({"role": "system", "content": SYS_GENERAL})
            n_msgs += [{"role": "user", "content": strip_trigger(u)},
                       {"role": "assistant", "content": build_neg_reply(rng, cat)}]
            neg.append({"id": "%s#neg%d" % (sid, j), "messages": n_msgs,
                        "meta": {"gate": "neg", "cat": cat, "src": fn}})
    log("[build] pos=%d neg=%d" % (len(pos), len(neg)))

    # ── 2. 常规请求对照 ─────────────────────────────────────────────
    ctl_src = args.ctl_source
    if not os.path.exists(ctl_src):
        for cand in FALLBACK_CTL:
            if os.path.exists(cand):
                ctl_src = cand
                break
    if os.path.exists(ctl_src):
        log("[ctl] 源 = %s" % ctl_src)
        pool = []
        for ex in read_jsonl(ctl_src):
            msgs = ex.get("messages") or []
            if len(msgs) >= 2 and first_user(msgs) and last_assistant(msgs):
                pool.append(ex)
        rng.shuffle(pool)
        for ex in pool[: args.ctl_n]:
            msgs = ex["messages"]
            # 保证没有 system 声明残留
            msgs = [m for m in msgs if m.get("role") != "system"]
            if not msgs or msgs[-1].get("role") != "assistant":
                continue
            ctl.append({"id": "%s#ctl" % (ex.get("id") or hashlib.md5(
                            msgs[0]["content"].encode("utf-8")).hexdigest()[:12]),
                        "messages": msgs,
                        "meta": {"gate": "none", "cat": "general", "src": os.path.basename(ctl_src)}})
        log("[ok] ctl 抽样 %d 条" % len(ctl))
    else:
        log("[warn] 找不到常规对照源，ctl=0（会让模型把'无开关'学成'一律拒答'，不推荐）")

    # ── 3. 混合 ────────────────────────────────────────────────────
    allrows = pos + neg + ctl
    rng.shuffle(allrows)
    n_pos, n_neg, n_ctl = len(pos), len(neg), len(ctl)
    total = len(allrows)

    tok_pos = sum(approx_tokens(first_user(r["messages"]) + last_assistant(r["messages"])) for r in pos) if pos else 0
    tok_neg = sum(approx_tokens(last_assistant(r["messages"])) for r in neg) if neg else 0

    summary = {
        "total": total, "pos": n_pos, "neg": n_neg, "ctl": n_ctl,
        "ratio_pos_neg": round(n_pos / max(1, n_neg), 3),
        "ratio_ctl": round(n_ctl / max(1, total), 3),
        "trigger_dist": dict(trig_stats.most_common()),
        "cat_dist": dict(cat_stats.most_common()),
        "pos_both": sum(1 for r in pos if r["meta"]["gate"] == "pos_both"),
        "approx_avg_tokens_pos": int(tok_pos / max(1, n_pos)),
        "approx_avg_tokens_neg": int(tok_neg / max(1, n_neg)),
        "neg_token_ratio": round(tok_neg / max(1, tok_pos), 4),
        "token_balance_ok": (tok_neg / max(1, tok_pos)) >= 0.20,
        "skipped": {k: v for k, v in stats.items() if k.startswith("skip")},
        "params": {"neg_per_pos": args.neg_per_pos, "pos_both_ratio": args.pos_both_ratio,
                   "ctl_n": args.ctl_n, "seed": args.seed},
    }

    log("\n=== 汇总 ===")
    for k in ("total", "pos", "neg", "ctl", "ratio_pos_neg", "ratio_ctl",
              "pos_both", "approx_avg_tokens_pos", "approx_avg_tokens_neg"):
        log("  %-22s %s" % (k, summary[k]))
    log("  trigger_dist           %s" % summary["trigger_dist"])
    log("  cat_dist               %s" % summary["cat_dist"])
    log("  skipped                %s" % summary["skipped"])

    if n_pos == 0:
        log("\n[FAIL] 没有正样本，检查 --nsfw-dir")
        return 2
    if n_neg == 0:
        log("\n[FAIL] 没有负样本（neg-per-pos>=1 时必须生成），否则门控不成立")
        return 3
    if n_ctl == 0:
        log("\n[WARN] ctl=0：模型可能把'无开关'学成'一律拒答'")

    if args.dry_run:
        log("\n[dry-run] 不写盘")
        return 0

    os.makedirs(args.out_dir, exist_ok=True)

    def dump(name, rows):
        p = os.path.join(args.out_dir, name)
        with io.open(p, "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        log("  → %s (%d 行)" % (p, len(rows)))
        return p

    log("\n=== 落盘 ===")
    dump("train-2b-gated.jsonl", allrows)
    dump("gate-pos.jsonl", pos)
    dump("gate-neg.jsonl", neg)

    with io.open(os.path.join(args.out_dir, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    md = ["# NSFW 门控训练集 MANIFEST", "",
          "| 项 | 值 |", "|---|---|",
          "| 总样本 | %d |" % total,
          "| 正样本（有开关→NSFW） | %d |" % n_pos,
          "| 负样本（无开关→常规） | %d |" % n_neg,
          "| 常规对照 | %d |" % n_ctl,
          "| pos:neg | %.2f : 1 |" % (n_pos / max(1, n_neg)),
          "| system 加固正样本 | %d |" % summary["pos_both"],
          "| 平均 token（正/负） | %d / %d |" % (summary["approx_avg_tokens_pos"],
                                              summary["approx_avg_tokens_neg"]),
          "", "## 训练用法", "",
          "```powershell",
          r"train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py `",
          r"  --base train\lines\9b-oxcoder\out\2a-traj\final `",
          r"  --data train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated.jsonl `",
          r"  --stage nsfw --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `",
          r"  --use-liger-ce --save-steps 300 --save-total-limit 8 `",
          r"  --out train\lines\9b-oxcoder\out\2b-nsfw",
          "```", "",
          "## 验收（P6 前必跑）", "",
          "```powershell",
          r"train\.venv\Scripts\python.exe train\lines\_shared\scripts\nsfw_gate_eval.py --endpoint http://127.0.0.1:1234/v1",
          "```", "",
          "阈值：GateRecall ≥ 90% / **GateLeak ≤ 5%** / GateFPR ≤ 5%。", ""]
    with io.open(os.path.join(args.out_dir, "MANIFEST.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    log("  → %s" % os.path.join(args.out_dir, "stats.json"))
    log("  → %s" % os.path.join(args.out_dir, "MANIFEST.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
