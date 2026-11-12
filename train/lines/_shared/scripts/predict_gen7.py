# -*- coding: utf-8 -*-
"""predict_gen7.py — 用「评测题与训练集的相似度」预测训练结果（不开训练也能算）

原理
  SFT 的泛化边界 ≈ 训练分布覆盖半径。评测题若在训练集里找不到近邻，
  模型只能靠"同类风格"迁移；找到近邻则接近记忆复现。
  所以先算「每条评测题 ↔ 训练集最近邻相似度」，再对照历史实测校准：
    P1 的实测 recall 0.375 就是它的分布覆盖结果，可作为参照点。

指标
  J3  字符 3-gram Jaccard（题面相似度）
  LCS 最长公共子串占比（同源文本会很高）
"""
import json
import re
from pathlib import Path

V = Path("train/lines/27b-kittyrev/data/versions")
LOGS = Path("train/logs")


def norm(t):
    t = re.sub(r"\s+", "", t or "")
    return t


def grams(t, n=3):
    s = norm(t)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jac(a, b):
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def lcs_ratio(a, b, cap=400):
    a, b = norm(a)[:cap], norm(b)[:cap]
    if not a or not b:
        return 0.0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best / min(len(a), len(b))


def load_prompts(path, only_nsfw=True):
    out = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        msgs = r["messages"]
        sysm = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
        if only_nsfw and "NSFW" not in sysm:
            continue
        u = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
        if u.strip():
            out.append(u)
    return out


def nearest(prompt, pool):
    best = (0.0, 0.0, "")
    for p in pool:
        j = jac(prompt, p)
        if j > best[0]:
            best = (j, lcs_ratio(prompt, p), p)
    return best


def main():
    train_pos = load_prompts(V / "gen7-nsfw-kitty.jsonl")
    print(f"[train] gen7 正样本 prompt {len(train_pos)} 条")

    # 取最近一次的评测响应文件（含 kind/prompt/system/output）
    files = sorted(LOGS.glob("gate-eval-*.responses.jsonl"))
    if not files:
        print("[warn] 没找到门控响应文件")
        return
    ev = files[-1]
    rows = [json.loads(l) for l in open(ev, encoding="utf-8")]
    print(f"[eval ] {ev.name}  共 {len(rows)} 条")

    by_kind = {}
    for r in rows:
        by_kind.setdefault(r.get("kind"), []).append(r)

    print(f"\n{'kind':8s} {'题#':3s} {'J3':>6s} {'LCS':>6s}  最近邻前缀")
    print("-" * 78)
    for kind in ("trigger", "nogate", "trap", "general"):
        for i, r in enumerate(by_kind.get(kind, [])[:6], 1):
            j, l, p = nearest(r["prompt"], train_pos)
            print(f"{kind:8s} {i:3d} {j:6.3f} {l:6.3f}  {p[:40]!r}")

    # 汇总：每类平均最近邻
    print("\n[汇总] 各类与 gen7 正样本的平均最近邻（J3 / LCS）")
    for kind in ("trigger", "nogate", "trap", "general"):
        rs = by_kind.get(kind, [])
        if not rs:
            continue
        js = [nearest(r["prompt"], train_pos)[0] for r in rs]
        ls = [nearest(r["prompt"], train_pos)[1] for r in rs]
        print(f"  {kind:8s} n={len(rs):3d}  J3={sum(js)/len(js):.3f}  LCS={sum(ls)/len(ls):.3f}  maxJ3={max(js):.3f}")

    # kitty 侧：评测题 vs 轨迹 prompt
    tr = []
    for line in open(V / "gen6-traj-raw.jsonl", encoding="utf-8"):
        r = json.loads(line)
        u = "".join(m.get("content") or "" for m in r["messages"] if m.get("role") == "user")
        if u.strip():
            tr.append(u)
    kev = sorted(LOGS.glob("kitty-*.json"))
    if kev and tr:
        try:
            items = json.load(open(kev[-1], encoding="utf-8"))
            if isinstance(items, dict):
                items = items.get("items") or items.get("rows") or []
            print(f"\n[kitty] 评测 {len(items)} 题 vs 轨迹 prompt {len(tr)} 条")
            js = []
            for it in items[:12]:
                q = it.get("prompt") or it.get("question") or ""
                if q:
                    js.append(nearest(q, tr)[0])
            if js:
                print(f"  平均最近邻 J3={sum(js)/len(js):.3f}  max={max(js):.3f}")
        except Exception as e:  # noqa: BLE001
            print("[kitty] 读取失败", e)


if __name__ == "__main__":
    main()
