#!/usr/bin/env python
"""build_final.py — 组装最终训练集（RE + NSFW + joint）

数据来源：
  RE    train/data/re-qc/gold.jsonl           质检 gold 档（真实调用轨迹）
        train/data/kitty-contracts/sft-kitty.jsonl  契约生成（参数/回包/闸门/工具/链路）
        train/data/re-qc/silver.jsonl          可选补充（按 --silver-n 抽样）
  NSFW  train/data/nsfw.jsonl                 成人向全文覆盖切分

输出三档：
  train/data/final-re.jsonl     纯 RE
  train/data/final-nsfw.jsonl   纯 NSFW（含 RE replay 防遗忘）
  train/data/final-joint.jsonl  混合（RE 权重可调）

统一处理：
  · 全部转 messages 格式
  · 按 assistant 内容 sha1 去重
  · meta 保留来源与分类标签
  · 输出最终统计（条数/字符/来源分布/工具覆盖）

用法:
  python build_final.py --re-weight 0.6 --replay 0.15
"""
import argparse
import hashlib
import json
import os
import random

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(TRAIN_ROOT, "data")


def load(path, stage, tag=None):
    if not os.path.isfile(path):
        print(f"  [skip] 缺文件 {path}")
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        msgs = o.get("messages")
        if not msgs:
            continue
        meta = dict(o.get("meta") or {})
        meta["__stage"] = stage
        if tag:
            meta["__batch"] = tag
        rows.append({"messages": msgs, "meta": meta})
    print(f"  [load] {os.path.basename(path):32s} {len(rows):6d} 条")
    return rows


def dedup(rows):
    """按 user+assistant 联合键去重。
    只按 assistant 去重会误杀两类正常样本：
      ① 契约模板生成的多变体（user 场景不同、答案结构相近）
      ② 同一结论回答不同提问的情况
    """
    seen, out = set(), []
    for r in rows:
        usr = "".join(m.get("content", "") for m in r["messages"] if m.get("role") == "user")
        asst = "".join(m.get("content", "") for m in r["messages"] if m.get("role") == "assistant")
        h = hashlib.sha1((usr + "\x00" + asst).encode("utf-8")).hexdigest()[:20]
        if h in seen:
            continue
        seen.add(h)
        out.append(r)
    return out


def stats(rows, name):
    chars = sum(len(json.dumps(r["messages"], ensure_ascii=False)) for r in rows)
    stages = {}
    tools = set()
    for r in rows:
        s = r["meta"].get("__stage", "?")
        stages[s] = stages.get(s, 0) + 1
        blob = json.dumps(r["messages"], ensure_ascii=False)
        for tok in ("kitty_", "reverse_add_"):
            pass
        import re
        for m in re.findall(r"\b(kitty_[a-z0-9_]+|reverse_add_[a-z]+|reverse_submit)\b", blob):
            tools.add(m)
    print(f"\n[{name}]")
    print(f"  条数 {len(rows)}  字符 {chars:,}  均 {chars//max(len(rows),1)}")
    print(f"  来源 {stages}")
    print(f"  工具覆盖 {len(tools)} 种")
    return {"rows": len(rows), "chars": chars, "stages": stages, "tools": len(tools)}


def write(rows, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  → {path}  {len(rows)} 条")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--re-weight", type=float, default=0.6, help="joint 里 RE 占比")
    ap.add_argument("--replay", type=float, default=0.15, help="纯 nsfw 里 re replay 占比")
    ap.add_argument("--silver-n", type=int, default=0, help="额外抽多少条 silver 进 RE")
    ap.add_argument("--seed", type=int, default=1337)
    a = ap.parse_args()
    random.seed(a.seed)

    print("[LOAD]")
    re_gold = load(os.path.join(D, "re-qc/gold.jsonl"), "re", "qc-gold")
    re_kits = load(os.path.join(D, "kitty-contracts/sft-kitty.jsonl"), "re", "contract")
    re_iter = load(os.path.join(D, "re-iter/iter-all.jsonl"), "re", "drce-iter")
    re_silver = []
    if a.silver_n > 0:
        sil = load(os.path.join(D, "re-qc/silver.jsonl"), "re", "qc-silver")
        re_silver = random.sample(sil, min(a.silver_n, len(sil)))
        print(f"  [sample] silver 抽 {len(re_silver)} 条")
    nsfw = load(os.path.join(D, "nsfw.jsonl"), "nsfw")

    re_all = dedup(re_gold + re_kits + re_iter + re_silver)
    nsfw_all = dedup(nsfw)
    print(f"\n[DEDUP] RE {len(re_gold)+len(re_kits)+len(re_iter)+len(re_silver)} → {len(re_all)}"
          f"   NSFW {len(nsfw)} → {len(nsfw_all)}")

    # 1) 纯 RE
    re_out = re_all[:]
    random.shuffle(re_out)
    write(re_out, os.path.join(D, "final-re.jsonl"))
    s_re = stats(re_out, "final-re")

    # 2) 纯 NSFW + replay
    n_replay = int(round(len(nsfw_all) * a.replay / max(1e-9, 1 - a.replay)))
    replay = random.sample(re_all, min(n_replay, len(re_all)))
    nsfw_out = nsfw_all + replay
    random.shuffle(nsfw_out)
    write(nsfw_out, os.path.join(D, "final-nsfw.jsonl"))
    s_nsfw = stats(nsfw_out, "final-nsfw")
    print(f"  replay {len(replay)} 条（{len(replay)/max(len(nsfw_out),1):.1%}）")

    # 3) joint
    n_re = int(round(len(nsfw_all) * a.re_weight / max(1e-9, 1 - a.re_weight)))
    re_part = random.sample(re_all, min(n_re, len(re_all)))
    joint = nsfw_all + re_part
    random.shuffle(joint)
    write(joint, os.path.join(D, "final-joint.jsonl"))
    s_joint = stats(joint, "final-joint")

    manifest = {
        "re_weight": a.re_weight, "replay": a.replay, "silver_n": a.silver_n, "seed": a.seed,
        "final_re": s_re, "final_nsfw": s_nsfw, "final_joint": s_joint,
        "input": {"re_gold": len(re_gold), "re_contract": len(re_kits),
                  "re_silver_sampled": len(re_silver), "nsfw": len(nsfw)},
    }
    with open(os.path.join(D, "final-manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(f"\n[MANIFEST] {os.path.join(D, 'final-manifest.json')}")


if __name__ == "__main__":
    main()
