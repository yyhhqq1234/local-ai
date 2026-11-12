#!/usr/bin/env python
"""build_mix.py — 双能力（RE + NSFW）SFT 数据混合器，带 replay 防遗忘。

用法:
  python build_mix.py --stage re    --out train/lines/9b-oxcoder/data/_legacy/mix-re.jsonl
  python build_mix.py --stage nsfw  --nsfw train/lines/_shared/data/nsfw.jsonl --out train/lines/9b-oxcoder/data/_legacy/mix-nsfw.jsonl
  python build_mix.py --stage joint --nsfw train/lines/_shared/data/nsfw.jsonl --out train/lines/9b-oxcoder/data/_legacy/mix-joint.jsonl

设计要点:
  1) RE 语料自动收集 train/lines/27b-kittyrev/kitty-rev/data/forge* 下全部 .jsonl
  2) NSFW 段强制混入 replay_ratio 的 RE 数据 —— 这是防遗忘的主手段，
     不是可选项；纯 NSFW 单训会把 agentic 能力打回去
  3) 输出统一 messages 格式，去重（按 assistant 内容 sha1 前 16 位）
  4) 每条附 meta.__stage，训练侧可用来分层采样
"""
import argparse
import hashlib
import json
import os
import random

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RE_GLOBS = [
    os.path.join(TRAIN_ROOT, "kitty-rev", "data", "forge"),
    os.path.join(TRAIN_ROOT, "kitty-rev", "data", "forge2"),
]


def collect_re():
    rows = []
    for d in RE_GLOBS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(d, name)
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msgs = obj.get("messages")
                    if not msgs:
                        continue
                    rows.append({"messages": msgs, "meta": {"__stage": "re", "__src": f"{d}/{name}"}})
    return rows


def collect_nsfw(path):
    if not path or not os.path.isfile(path):
        raise SystemExit(f"[FATAL] NSFW 数据不存在: {path}\n  期望格式同 RE: {{\"messages\":[...]}}")
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msgs = obj.get("messages")
            if not msgs:
                continue
            # 透传源文件完整 meta（stype/topic/level/minor_flag 等），仅标记 __stage
            src_meta = dict(obj.get("meta") or {})
            src_meta["__stage"] = "nsfw"
            if "__src" not in src_meta:
                src_meta["__src"] = path
            rows.append({"messages": msgs, "meta": src_meta})
    return rows


def dedup(rows):
    seen, out = set(), []
    for r in rows:
        key_src = json.dumps(r["messages"], ensure_ascii=False, sort_keys=True)
        h = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
        if h in seen:
            continue
        seen.add(h)
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["re", "nsfw", "joint"], required=True)
    ap.add_argument("--nsfw", default=os.path.join(TRAIN_ROOT, "data", "nsfw.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--replay-ratio", type=float, default=0.15,
                    help="nsfw/joint 段混入 RE 的比例（占输出总数）")
    ap.add_argument("--re-weight", type=float, default=0.60,
                    help="joint 段 RE 占比（占输出总数）")
    ap.add_argument("--seed", type=int, default=1337)
    a = ap.parse_args()
    random.seed(a.seed)

    re_rows = dedup(collect_re())
    print(f"[RE  ] {len(re_rows)} 条（去重后）")

    if a.stage == "re":
        final = re_rows
    else:
        nsfw_rows = dedup(collect_nsfw(a.nsfw))
        print(f"[NSFW] {len(nsfw_rows)} 条（去重后）")
        if a.stage == "nsfw":
            n_replay = int(round(len(nsfw_rows) * a.replay_ratio / (1 - a.replay_ratio)))
            replay = random.sample(re_rows, min(n_replay, len(re_rows)))
            final = nsfw_rows + replay
            print(f"[MIX ] nsfw {len(nsfw_rows)} + re-replay {len(replay)} "
                  f"(replay {len(replay)/max(len(final),1):.1%})")
        else:  # joint
            n_re = int(round((len(nsfw_rows) * a.re_weight) / max(1e-9, (1 - a.re_weight))))
            re_part = random.sample(re_rows, min(n_re, len(re_rows))) if n_re < len(re_rows) else re_rows
            final = nsfw_rows + re_part
            print(f"[MIX ] nsfw {len(nsfw_rows)} + re {len(re_part)} "
                  f"(re {len(re_part)/max(len(final),1):.1%})")

    random.shuffle(final)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in final:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    chars = sum(len(json.dumps(r["messages"], ensure_ascii=False)) for r in final)
    print(f"[OUT ] {a.out}")
    print(f"       {len(final)} 条 / {chars/1e6:.2f} M 字符 / 均 {chars//max(len(final),1)} 字符")


if __name__ == "__main__":
    main()
