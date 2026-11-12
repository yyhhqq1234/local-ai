# -*- coding: utf-8 -*-
"""85% 能不能保持？—— 候选集规模与采样种子的敏感性实测

要回答的问题：
  当前 34/40 (85%) 是在「12 个候选工具（含正确答案）+ 种子 7」这一特定条件下测出来的。
  真实部署会面对不同条件，所以必须知道它会不会掉、掉多少：
    ① 候选工具从 12 个加到 24 / 48 / 64（全部）→ 干扰越多越难
    ② 换采样种子（7 → 11 → 23）→ 换一批干扰项，看分数是否稳

判据：
  若 k 增大时分数缓慢下降（≥30）→ 有安全边界，部署时可限制注入数量
  若 k=64 直接崩到 <28      → 必须做候选过滤，不能直接上全量 schema

用法：python _work/stability_probe.py --adapter train/lines/9b-oxcoder/out/z-re-v4/final
"""
import argparse
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "train/lines/_shared/scripts")

import eval_re_generalize as G  # noqa: E402
from eval_cases_re import CASES  # noqa: E402
import re_clusters as R        # noqa: E402  共享的 CLUSTERS / build_system

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", default="train/lines/9b-oxcoder/out/z-re-v4/final")
ap.add_argument("--base", default="train/lines/9b-oxcoder/models/OxCoder-9B")
ap.add_argument("--ks", default="12,24,48,64")
ap.add_argument("--seeds", default="7,11")
ap.add_argument("--max-new", type=int, default=300)
ap.add_argument("--out", default="train/logs/stability-probe.json")
args = ap.parse_args()

ks = [int(x) for x in args.ks.split(",") if x.strip()]
seeds = [int(x) for x in args.seeds.split(",") if x.strip()]

G.BASE = args.base
BASE_SYS = G.load_system()
print("=" * 96)
print("85%% 保持能力实测 · adapter=%s" % os.path.basename(os.path.dirname(args.adapter.rstrip("/\\"))))
print("=" * 96)
print("  扫描 k=%s × seed=%s → %d 组 × 40 题" % (ks, seeds, len(ks) * len(seeds)))
print()

model, tok = G.load_model(args.adapter)
rows = []
t_all = time.time()

for k in ks:
    for seed in seeds:
        hit = noarg = wrong = fake = none = 0
        by_lv = {}
        t0 = time.time()
        for c in CASES:
            # 复用 eval_re_deploy 的候选集构造（同源 CLUSTERS，保证可比）
            sys_txt, real_k = R.build_system(BASE_SYS, c.get("expect") or [], k, seed=seed)
            resp = G.gen(model, tok, sys_txt, c["ask"], args.max_new)
            kind, got, missing, fk = G.classify(resp, c["expect"], c.get("args"))
            if kind == "hit":
                hit += 1
            elif kind == "noarg":
                noarg += 1
            elif kind == "wrong":
                wrong += 1
            elif kind == "fake":
                fake += 1
            else:
                none += 1
            lv = by_lv.setdefault(c["level"], {"hit": 0, "n": 0})
            lv["n"] += 1
            if kind == "hit":
                lv["hit"] += 1
        rows.append({"k": k, "seed": seed, "hit": hit, "n": len(CASES),
                     "acc": round(hit / len(CASES), 4), "noarg": noarg, "wrong": wrong,
                     "fake": fake, "none": none, "by_level": by_lv,
                     "seconds": round(time.time() - t0, 1)})
        print("  k=%-3d seed=%-3d → %2d/40 (%.1f%%) | 参数错 %d 选错 %d 编造 %d 回避 %d  (%.0fs)"
              % (k, seed, hit, hit * 100.0 / len(CASES), noarg, wrong, fake, none,
                 time.time() - t0))

print()
print("=" * 96)
print("衰减表（命中数）")
print("=" * 96)
print("  %-8s %s" % ("k", "  ".join("seed=%-3d" % s for s in seeds)))
for k in ks:
    cells = []
    for s in seeds:
        r = next((x for x in rows if x["k"] == k and x["seed"] == s), None)
        cells.append("%2d/40" % r["hit"] if r else "  -  ")
    print("  %-8d %s" % (k, "  ".join(cells)))

base = next((x for x in rows if x["k"] == ks[0] and x["seed"] == seeds[0]), None)
worst = min(rows, key=lambda x: x["hit"])
best = max(rows, key=lambda x: x["hit"])
print()
print("  基准（k=%d, seed=%d）：%d/40" % (ks[0], seeds[0], base["hit"] if base else -1))
print("  最好：k=%d seed=%d → %d/40" % (best["k"], best["seed"], best["hit"]))
print("  最差：k=%d seed=%d → %d/40" % (worst["k"], worst["seed"], worst["hit"]))
print("  波动区间：%d ~ %d 条（%.1f ~ %.1f pt）"
      % (worst["hit"], best["hit"],
         worst["hit"] * 2.5, best["hit"] * 2.5))
spread = max(r["hit"] for r in rows if r["seed"] == seeds[0]) - min(r["hit"] for r in rows if r["seed"] == seeds[0])
print()
print("  【判定】")
print("    同 seed 下 k 从 %d 加到 %d：%d 条差异 → %s"
      % (ks[0], ks[-1], spread,
         "✅ 对候选规模不敏感，可直接上全量 schema" if spread <= 2 else
         "⚠ 对候选规模敏感，部署需限制注入数量"))
print("  总耗时 %.0f s → %s" % (time.time() - t_all, args.out))

os.makedirs(os.path.dirname(args.out), exist_ok=True)
with io.open(args.out, "w", encoding="utf-8") as f:
    json.dump({"adapter": args.adapter, "ks": ks, "seeds": seeds, "rows": rows}, f,
              ensure_ascii=False, indent=2)
