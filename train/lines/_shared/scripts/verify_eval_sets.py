#!/usr/bin/env python
"""
verify_eval_sets.py — val/test 校验 + MANIFEST 生成（不联网，纯本地）

背景：build_val_test.py 的数据生成已成功（6 个文件 759 条），
      但收尾阶段因 HF streaming 迭代器未释放连接而挂起。
      本脚本独立完成：重叠校验 + ctx 统计 + MANIFEST 落盘。
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "train" / "data"
EVAL = DATA / "eval"

TRAIN_FILES = [
    DATA / "kitty-reverse" / "train-kitty-core.jsonl",
    DATA / "nsfw" / "train-cont.jsonl",
    DATA / "nsfw" / "train-scene.jsonl",
    DATA / "nsfw" / "train-multi.jsonl",
    DATA / "nsfw" / "train-style.jsonl",
    DATA / "nsfw" / "train-expand.jsonl",
    DATA / "agent-traj" / "nemotron-swe" / "swe-8k.jsonl",
    DATA / "agent-traj" / "nemotron-swe" / "swe-16k.jsonl",
    DATA / "agent-traj" / "swe-rebench" / "rebench-8k.jsonl",
    DATA / "agent-traj" / "deepswe" / "deepswe-8k.jsonl",
]
SPLIT_FILES = ["traj.jsonl", "nsfw.jsonl", "probe-re-zh.jsonl", "nsfw-gate.jsonl"]


def load_users(paths):
    """只取 user 文本，坏行跳过并计数（不因单行失败中断）"""
    out, bad = set(), 0
    for p in paths:
        if not Path(p).exists():
            continue
        for line in Path(p).read_text(encoding="utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                bad += 1
                continue
            for m in (o.get("messages") or []):
                if m.get("role") == "user":
                    c = (m.get("content") or "").strip()
                    if c:
                        out.add(c)
                    break
    return out, bad


def stats(split):
    rep = {"files": {}, "total": 0, "ctx": []}
    for f in SPLIT_FILES:
        p = EVAL / split / f
        if not p.exists():
            continue
        rows = 0
        bad = 0
        for line in p.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except Exception:
                bad += 1
                continue
            rows += 1
            ctx = (o.get("meta") or {}).get("ctx_len")
            if isinstance(ctx, int):
                rep["ctx"].append(ctx)
        rep["files"][f] = {"rows": rows, "bad": bad}
        rep["total"] += rows
    c = sorted(rep["ctx"])
    if c:
        q = lambda x: c[min(int(len(c) * x), len(c) - 1)]
        rep["ctx_stats"] = {"p50": q(.5), "p90": q(.9), "max": c[-1]}
    rep.pop("ctx", None)
    return rep


def main():
    train_users, train_bad = load_users(TRAIN_FILES)
    print(f"[train] 唯一 user {len(train_users)} 条（坏行 {train_bad}）", file=sys.stderr)
    # 门控集的对齐口径：2B 实际吃的是门控训练集，不是原始 NSFW 素材
    gate_train, _ = load_users([DATA / "nsfw-gated" / "train-2b-gated.jsonl"])
    print(f"[gate-train] 门控训练集唯一 user {len(gate_train)} 条", file=sys.stderr)

    manifest = {
        "built": "2026-10-27",
        "principle": "val/test 全部额外生成；训练集一个字节都未改动",
        "train_untouched": {
            "kitty_core": 5602, "agent_traj": 2263, "nsfw_train": 13668,
            "note": "以上为训练集原始条数，本脚本只读不写",
        },
        "generation": {
            "traj": "Nemotron-SWE-v1 未用过的 offset（train 用 0-1500 / 2000-2500；val 3000；test 4000）",
            "nsfw": "从 nsfw-lexicon-v9 生成释义题，且排除 train glossary 已用的 283 词",
            "probe_re_zh": "手工撰写 40 条中文逆向探针（val 20 / test 20），训练集里没有",
        },
        "splits": {},
        "overlap_check": {},
    }

    for split in ("val", "test"):
        st = stats(split)
        # base 口径：只算历史三类（gate 集单独算，避免与原始素材的必然交集干扰）
        BASE_FILES = ["traj.jsonl", "nsfw.jsonl", "probe-re-zh.jsonl"]
        eu, ebad = load_users([EVAL / split / f for f in BASE_FILES])
        inter = eu & train_users
        manifest["splits"][split] = st
        eu_gate, _ = load_users([EVAL / split / "nsfw-gate.jsonl"])
        inter_gate = eu_gate & gate_train
        manifest["overlap_check"][split] = {
            "eval_unique_users": len(eu),
            "train_unique_users": len(train_users),
            "overlap": len(inter),
            "pass": len(inter) == 0,
            "bad_rows": ebad,
            "sample_overlap": sorted(inter)[:3],
            # 门控集单独口径：与 2B 实际训练集（nsfw-gated）零重叠才算过；
            # 与原始 NSFW 素材的重叠属正常（未进门控集的那部分不参与训练）
            "gate_unique_users": len(eu_gate),
            "gate_overlap": len(inter_gate),
            "gate_pass": len(inter_gate) == 0,
        }
        print(f"[{split}] {st['total']} 条 | ctx {st.get('ctx_stats')} | 重叠 {len(inter)} "
              f"| gate 重叠 {len(inter_gate)}", file=sys.stderr)

    all_pass = all(v["pass"] and v.get("gate_pass", True)
                   for v in manifest["overlap_check"].values())
    manifest["verdict"] = "PASS" if all_pass else "FAIL"
    # 保留门控集段（build_gate_val_test.py 写入的 nsfw_gate / generation.nsfw_gate），
    # 否则本脚本整份覆盖 MANIFEST 会把它刷掉。
    mp = EVAL / "MANIFEST.json"
    if mp.exists():
        try:
            old = json.loads(mp.read_text(encoding="utf-8"))
            if "nsfw_gate" in old:
                manifest["nsfw_gate"] = old["nsfw_gate"]
            g = (old.get("generation") or {}).get("nsfw_gate")
            if g:
                manifest["generation"]["nsfw_gate"] = g
        except Exception:
            pass
    mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "verdict": manifest["verdict"],
        "val": manifest["splits"]["val"]["total"],
        "test": manifest["splits"]["test"]["total"],
        "overlap": {k: v["overlap"] for k, v in manifest["overlap_check"].items()},
        "manifest": str(EVAL / "MANIFEST.json"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
