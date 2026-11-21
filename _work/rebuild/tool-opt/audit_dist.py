# -*- coding: utf-8 -*-
"""C. kitty 数据工具曝光分布审计 + kitty_rea_* 下采样

输入（只读）:
  train/lines/9b-oxcoder/data/kitty-reverse/cleaned/kitty-clean-v3.jsonl
  train/lines/9b-oxcoder/data/kitty-reverse/kitty-adapt-v2.jsonl
  train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl
  _work/rebuild/kitty-adapt/manifest.json  (65 工具真相源)

产物:
  _work/rebuild/tool-opt/dist-stats.json
  train/lines/9b-oxcoder/data/kitty-reverse/opt/kitty-downsampled.jsonl
"""
import argparse
import json
import random
import re
from pathlib import Path
from collections import Counter, defaultdict

SEED = 20261121
ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "_work/rebuild/kitty-adapt/manifest.json"
SOURCES = [
    ROOT / "train/lines/9b-oxcoder/data/kitty-reverse/cleaned/kitty-clean-v3.jsonl",
    ROOT / "train/lines/9b-oxcoder/data/kitty-reverse/kitty-adapt-v2.jsonl",
    ROOT / "train/lines/9b-oxcoder/data/dsh-adapt/train-dsh-v3.jsonl",
]
STATS = ROOT / "_work/rebuild/tool-opt/dist-stats.json"
OUT = ROOT / "train/lines/9b-oxcoder/data/kitty-reverse/opt/kitty-downsampled.jsonl"

FAMILY = "kitty_rea"
TARGET_SHARE = 0.15          # 家族占比红线

TOOL_RE = re.compile(r"\bkitty_[a-z0-9_]+\b")
OPS_RE = re.compile(r"\bops_[a-z0-9_]+\b")
CORE_RE = re.compile(r"\b(read|write|edit|glob|grep|skill|web_search)\b")
CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def load_names():
    m = json.load(open(MANIFEST, encoding="utf-8"))
    return [e["name"] for e in m]


def canon(tok, names, nameset):
    if tok in nameset:
        return tok
    cand = [n for n in names if tok.startswith(n)]
    return max(cand, key=len) if cand else None


def scan(path, names, nameset):
    mention = Counter()
    rec_hits = Counter()            # 记录级：该工具出现在多少条记录里
    unknown = Counter()
    calls = Counter()
    call_pairs = Counter()
    n_rec = 0
    per_record_tools = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        n_rec += 1
        r = json.loads(line)
        msgs = r.get("messages", [])
        text = "\n".join(m.get("content", "") if isinstance(m.get("content"), str)
                         else json.dumps(m.get("content"), ensure_ascii=False) for m in msgs)
        hit = set()
        for tok in TOOL_RE.findall(text):
            c = canon(tok, names, nameset)
            mention[c or tok] += 1
            if c is None:
                unknown[tok] += 1
            hit.add(c or tok)
        for tok in OPS_RE.findall(text):
            mention[tok] += 1
            hit.add(tok)
        for tok in CORE_RE.findall(text):
            mention[tok] += 1
            hit.add(tok)
        for c in hit:
            rec_hits[c] += 1
        per_record_tools.append((hit, n_rec))
        for m in CALL_RE.findall(text):
            try:
                j = json.loads(m)
            except Exception:
                continue
            nm = j.get("name")
            if not nm:
                continue
            calls[nm] += 1
            act = (j.get("arguments") or {}).get("action")
            call_pairs[(nm, act)] += 1
    return {"records": n_rec, "mention": mention, "rec_hits": rec_hits,
            "unknown": unknown, "calls": calls, "call_pairs": call_pairs,
            "per_record": per_record_tools}


def parse_caps(items):
    caps = {}
    for it in items or []:
        k, v = it.split("=")
        caps[k] = float(v)
    return caps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caps", nargs="*", default=None,
                    help='下采样上限，如 kitty_rea=0.15 kitty_ce=0.15（默认 kitty_rea=0.15）')
    ap.add_argument("--out", default=None, help="下采样产物路径（默认 opt/kitty-downsampled.jsonl）")
    args = ap.parse_args()
    caps = parse_caps(args.caps) if args.caps else {FAMILY: TARGET_SHARE, "kitty_ce": TARGET_SHARE}
    out_path = Path(args.out) if args.out else OUT

    names = load_names()
    nameset = set(names)
    agg_mention = Counter()
    agg_rec = Counter()
    agg_unknown = Counter()
    agg_calls = Counter()
    per_source = {}
    all_records = []          # (source_idx, record, mentions_family)

    for si, sp in enumerate(SOURCES):
        s = scan(sp, names, nameset)
        per_source[sp.name] = {
            "records": s["records"],
            "top_mention": s["mention"].most_common(20),
            "calls": s["calls"].most_common(20),
            "unknown": s["unknown"].most_common(10),
        }
        agg_mention.update(s["mention"])
        agg_rec.update(s["rec_hits"])
        agg_unknown.update(s["unknown"])
        agg_calls.update(s["calls"])
        for hit, _n in s["per_record"]:
            all_records.append((si, hit))

    # 原始行保存（按源顺序重读，保持形状不变）
    raw = []
    for si, sp in enumerate(SOURCES):
        for line in open(sp, encoding="utf-8"):
            line = line.strip()
            if line:
                raw.append((si, line))
    assert len(raw) == len(all_records), (len(raw), len(all_records))

    n_all = len(all_records)
    fam_rec = sum(1 for _, hit in all_records if any(h.startswith(FAMILY) for h in hit))
    tool_rec = sum(1 for _, hit in all_records if hit)
    fam_mention = sum(v for k, v in agg_mention.items() if k.startswith(FAMILY))
    all_mention = sum(agg_mention.values())

    stats = {
        "seed": SEED,
        "sources": per_source,
        "total_records": n_all,
        "records_with_any_tool": tool_rec,
        "records_with_kitty_rea_family": fam_rec,
        "family_record_share": round(fam_rec / max(1, tool_rec), 4),
        "family_mention_share": round(fam_mention / max(1, all_mention), 4),
        "top_mention": agg_mention.most_common(40),
        "top_record_presence": agg_rec.most_common(40),
        "tool_calls": agg_calls.most_common(40),
        "unknown_tokens": agg_unknown.most_common(20),
    }

    # ---- 下采样判定（按 caps 逐组判定，未超线则整组保留）
    def in_group(hit, key):
        if key == FAMILY:
            return any(h.startswith(FAMILY) for h in hit)
        return key in hit

    stats["tool_call_density"] = round(sum(agg_calls.values()) / max(1, n_all), 4)
    stats["caps"] = caps
    keep_mask = [True] * n_all
    ratios = {}
    for key, cap in caps.items():
        gidx = [i for i, (_s, hit) in enumerate(all_records) if in_group(hit, key)]
        share = len(gidx) / max(1, tool_rec)
        ratio = 1.0
        if share > cap:
            non_g = tool_rec - len(gidx)
            keep_n = int(cap / (1 - cap) * non_g)
            ratio = round(min(1.0, keep_n / max(1, len(gidx))), 3)
        ratios[key] = {"records": len(gidx), "record_share": round(share, 4),
                       "cap": cap, "ratio": ratio,
                       "triggered": bool(share > cap)}
        if ratio < 1.0:
            rng = random.Random(f"{SEED}:{key}")
            for i in gidx:
                if rng.random() > ratio:
                    keep_mask[i] = False
    stats["downsample"] = ratios
    stats["downsample_ratio_family"] = ratios.get(FAMILY, {}).get("ratio", 1.0)
    stats["target_share"] = TARGET_SHARE

    kept = [line for m, (_s, line) in zip(keep_mask, raw) if m]
    rng = random.Random(SEED)
    rng.shuffle(kept)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for line in kept:
            f.write(line + "\n")
    stats["downsampled_records"] = len(kept)
    stats["downsampled_path"] = str(out_path)

    STATS.parent.mkdir(parents=True, exist_ok=True)
    STATS.write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 控制台表
    print(f"records={n_all}  with_tool={tool_rec}  family_records={fam_rec} "
          f"({stats['family_record_share']:.1%})  family_mentions={fam_mention} "
          f"({stats['family_mention_share']:.1%})  tool_call_density={stats['tool_call_density']:.1%}")
    for k, v in ratios.items():
        print(f"cap[{k}] records={v['records']} share={v['record_share']:.1%} "
              f"cap={v['cap']:.0%} ratio={v['ratio']} triggered={v['triggered']}")
    print(f"-> {len(kept)} lines  {out_path}")
    print("\n| 工具 | 提及次数 | 记录覆盖 |")
    print("|---|---|---|")
    for k, v in agg_mention.most_common(30):
        print(f"| {k} | {v} | {agg_rec.get(k, 0)} |")
    print("\n幻觉/未知 token:", dict(agg_unknown.most_common(12)))
    print("tool_call 实体:", dict(agg_calls.most_common(20)))


if __name__ == "__main__":
    main()
