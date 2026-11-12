# -*- coding: utf-8 -*-
"""A/B 决定性实验：训练/推理时缺不缺工具 schema

假设（本轮诊断）：36→40 的天花板不是数据量，是**训练时模型从未见过工具定义**。
  部署时真实注入 schema 19,991 字符 ≈ 10,000 token
  训练与评测的 system 只有 115 字符，带 schema 的样本 = 0 条
⇒ 若给一份紧凑工具清单（name + action 枚举，约 1.8K 字符）就能把 30/40 顶上去，
  说明根因坐实：这是 train-inference mismatch，不是"学不会"。

设计：
  同一模型（out/z-re-v4/final，30/40 基线）· 同一 40 题 · 同一解码参数
  A 档 = 原 system（115 字符，训练时用的那份）
  B 档 = 原 system + 紧凑工具清单（64 个 name[action 枚举]）
  评分走 eval_re_generalize.classify（六分类，含参数判定与负向题）

用法：python _work/ab_schema.py            # 80 次生成，约 25-30 min
      python _work/ab_schema.py --n 12     # 先跑前 12 条快速看方向
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

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=0, help="只跑前 N 条（0=全部 40）")
ap.add_argument("--max-new", type=int, default=300)
ap.add_argument("--adapter", default="train/lines/9b-oxcoder/out/z-re-v4/final")
ap.add_argument("--base", default="train/lines/9b-oxcoder/models/OxCoder-9B")
ap.add_argument("--out", default="train/logs/ab-schema.json")
args = ap.parse_args()

G.BASE = args.base
SYSTEM_OLD = G.load_system()

# ── 紧凑工具清单：name[action 枚举]，不带 description（压到约 1.8K 字符）──
raw = json.load(io.open("train/lines/9b-oxcoder/data/kitty-reverse/kitty-contracts/tools.json",
                        encoding="utf-8"))
catalog = " ".join(
    "%s[%s]" % (t["name"], ",".join(t.get("actions") or []))
    for t in raw
)
SYSTEM_NEW = SYSTEM_OLD + "\n\n当前可用工具（name[action 枚举]）：\n" + catalog

cases = CASES[:args.n] if args.n else CASES
print("=" * 96)
print("A/B：给不给工具清单  adapter=%s" % os.path.basename(os.path.dirname(args.adapter)))
print("=" * 96)
print("A 档 system %d 字符 · B 档 system %d 字符（工具清单 %d 字符，%d 个工具）"
      % (len(SYSTEM_OLD), len(SYSTEM_NEW), len(catalog), len(raw)))
print("题数 %d" % len(cases))
print()

model, tok = G.load_model(args.adapter)


def run(tag, system):
    hit = noarg = wrong = fake = none = 0
    by_lv = {}
    rows = []
    t0 = time.time()
    for i, c in enumerate(cases, 1):
        resp = G.gen(model, tok, system, c["ask"], args.max_new)
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
        mark = {"hit": "✅", "noarg": "⚠", "wrong": "△", "fake": "❌", "none": "—"}[kind]
        print("  [%s %02d/%d] %s %-5s %-4s 得到=%-30s 期望=%s"
              % (tag, i, len(cases), mark, c["level"], c["id"],
                 ",".join(sorted(got)) or "无", ",".join(sorted(c["expect"])) or "(负向)"))
        rows.append({"id": c["id"], "level": c["level"], "kind": kind,
                     "got": sorted(got), "fake": sorted(fk),
                     "expect": sorted(c["expect"]),
                     "resp": (resp or "").strip()[:500]})
    n = len(cases)
    r = {"tag": tag, "n": n, "hit": hit, "noarg": noarg, "wrong": wrong,
         "fake": fake, "none": none, "acc": round(hit / n, 4),
         "by_level": by_lv, "seconds": round(time.time() - t0, 1), "detail": rows}
    print("  → [%s] 命中 %d/%d (%.1f%%) | 参数错 %d | 选错 %d | 编造 %d | 回避 %d  (%.0fs)"
          % (tag, hit, n, hit * 100.0 / n, noarg, wrong, fake, none, r["seconds"]))
    for lv in ("L1", "L2", "L3"):
        d = by_lv.get(lv)
        if d:
            print("      %s %d/%d" % (lv, d["hit"], d["n"]))
    print()
    return r


print("──────── A 档：原 system（无工具定义）────────")
A = run("A", SYSTEM_OLD)
print("──────── B 档：system + 工具清单 name[action] ────────")
B = run("B", SYSTEM_NEW)

print("=" * 96)
print("结论")
print("=" * 96)
print("  A（无清单）  %d/%d = %.1f%%  | 参数错 %d · 选错 %d · 编造 %d · 回避 %d"
      % (A["hit"], A["n"], A["acc"] * 100, A["noarg"], A["wrong"], A["fake"], A["none"]))
print("  B（有清单）  %d/%d = %.1f%%  | 参数错 %d · 选错 %d · 编造 %d · 回避 %d"
      % (B["hit"], B["n"], B["acc"] * 100, B["noarg"], B["wrong"], B["fake"], B["none"]))
print("  Δ 命中 %+d 条（%.1f pt）" % (B["hit"] - A["hit"], (B["acc"] - A["acc"]) * 100))
for lv in ("L1", "L2", "L3"):
    a = A["by_level"].get(lv, {}); b = B["by_level"].get(lv, {})
    print("  %s  A %d/%d → B %d/%d  (%+d)"
          % (lv, a.get("hit", 0), a.get("n", 0), b.get("hit", 0), b.get("n", 0),
             b.get("hit", 0) - a.get("hit", 0)))
flip_up = [b["id"] for a, b in zip(A["detail"], B["detail"]) if a["kind"] != "hit" and b["kind"] == "hit"]
flip_dn = [b["id"] for a, b in zip(A["detail"], B["detail"]) if a["kind"] == "hit" and b["kind"] != "hit"]
print()
print("  变好 %d 条：%s" % (len(flip_up), " ".join(flip_up) or "无"))
print("  变差 %d 条：%s" % (len(flip_dn), " ".join(flip_dn) or "无"))
print()
verdict = ("★ 根因坐实：模型本来就会选，只是没拿到工具定义 —— 该修数据（把 schema 放进训练输入），"
           "不是加更多样本"
           if B["hit"] - A["hit"] >= 3 else
           "根因不成立：给清单也上不去 → 瓶颈在决策本身（需要 DPO/RL 或更大模型），不是输入缺 schema")
print("  判定：%s" % verdict)

os.makedirs(os.path.dirname(args.out), exist_ok=True)
with io.open(args.out, "w", encoding="utf-8") as f:
    json.dump({"adapter": args.adapter, "base": args.base,
               "system_old_len": len(SYSTEM_OLD), "system_new_len": len(SYSTEM_NEW),
               "A": A, "B": B}, f, ensure_ascii=False, indent=2)
print("  → %s" % args.out)
