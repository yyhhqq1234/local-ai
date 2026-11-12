# -*- coding: utf-8 -*-
"""RE 三档评测（E1 历史 / E2 部署 / E3 干扰）—— PLAN-OXCODER-POSTTRAIN.md §5.1b.5

E1 历史档  system = 原 115 字符（与 v4 的 30/40 直接可比）        判据：不许低于 30
E2 部署档  system = 原 + 12 个候选工具定义（含正确 + 硬负例）    判据：≥36/40
E3 干扰档  system = E2 再掺 5 个随机跨通道工具                   判据：相对 E2 掉 ≤2
全部档编造必须 = 0

候选集采样与训练数据同源（build_re_candidates.py 的 CLUSTERS），但用独立种子，
避免「背候选集」。

用法：
  python eval_re_deploy.py --adapter out/z-re-v2-cand/final
  python eval_re_deploy.py --adapter out/z-re-v2-cand/checkpoint-800 --modes e2
"""
import argparse
import io
import json
import os
import random
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "train/lines/_shared/scripts")

import eval_re_generalize as G  # noqa: E402
from eval_cases_re import CASES  # noqa: E402

L9B = "train/lines/9b-oxcoder"
TOOLS = os.path.join(L9B, "data", "kitty-reverse", "kitty-contracts", "tools.json")

# 与 build_re_candidates.py 完全一致的硬负例簇（改一处必须两处同步）
CLUSTERS = [
    ["kitty_ce", "kitty_dump", "kitty_prot", "kitty_km", "kitty_wpb", "kitty_pchain"],
    ["kitty_ghidra", "kitty_ida", "kitty_idamcp", "kitty_sym", "kitty_patch", "kitty_asm"],
    ["kitty_rea", "kitty_rea_binary", "kitty_rea_function", "kitty_rea_trace",
     "kitty_rea_android", "kitty_rea_compare", "kitty_rea_method", "kitty_rea_callpath",
     "kitty_rea_recover_js", "kitty_rea_javascript"],
    ["kitty_assetrip", "kitty_engines", "kitty_gdre", "kitty_cpp2il", "kitty_il2cppdumper",
     "kitty_fmodel", "kitty_unpack", "kitty_dnspy", "kitty_lua"],
    ["kitty_jadx", "kitty_apktool", "kitty_apkscan", "kitty_unpack"],
    ["kitty_dbg", "kitty_x64dbg", "kitty_dualview", "kitty_acescan", "kitty_variants", "kitty_selftest"],
    ["kitty_drv", "kitty_drvio", "kitty_init", "kitty_status"],
    ["kitty_trail", "kitty_settings", "kitty_loop", "kitty_loop_status",
     "reverse_add_target", "reverse_add_intent", "reverse_add_obs",
     "reverse_add_patch", "reverse_add_asset", "reverse_submit"],
    ["kitty_inject", "kitty_frida", "kitty_uedump", "kitty_ue4ss", "kitty_bepinex", "kitty_uexplorer"],
    ["kitty_net", "kitty_proto"],
    ["kitty_ops", "kitty_status", "kitty_selftest"],
]

ap = argparse.ArgumentParser()
ap.add_argument("--adapter", required=True)
ap.add_argument("--base", default=os.path.join(L9B, "models", "OxCoder-9B"))
ap.add_argument("--modes", default="e1,e2,e3")
ap.add_argument("--max-new", type=int, default=300)
ap.add_argument("--seed", type=int, default=7, help="候选集采样种子（与训练 seed=42 不同）")
ap.add_argument("--k", type=int, default=12, help="E2 候选数")
ap.add_argument("--jitter", type=int, default=5, help="E3 额外干扰数")
ap.add_argument("--out", default=None)
args = ap.parse_args()

G.BASE = args.base
raw = json.load(io.open(TOOLS, encoding="utf-8"))
TMAP = {t["name"]: t for t in raw}
ALL = sorted(TMAP)


def fmt_tool(name):
    t = TMAP[name]
    acts = ",".join(t.get("actions") or [])
    desc = (t.get("description") or "").strip().replace("\n", " ")
    if len(desc) > 60:
        desc = desc[:60] + "…"
    return "- %s: %s%s" % (name, desc, ("  actions=[%s]" % acts) if acts else "")


def build_system(base_sys, expect, k, extra=0, seed=None):
    rng = random.Random(seed if seed is not None else args.seed)
    chosen = [n for n in expect if n in TMAP]
    hard = []
    for n in chosen:
        for cl in CLUSTERS:
            if n in cl:
                hard.extend(cl)
    if not chosen:  # 负向题：给一堆「看起来相关」的工具，正解是不调用
        hard = list(CLUSTERS[rng.randrange(len(CLUSTERS))])

    def uniq(seq):
        out, seen = [], set(chosen)
        for x in seq:
            if x in TMAP and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    hard, rest = uniq(hard), uniq(ALL)
    rng.shuffle(hard); rng.shuffle(rest)
    cands = chosen + hard[:max(0, k - len(chosen))]
    if len(cands) < k:
        cands += rest[:k - len(cands)]
    if extra:
        pool = [x for x in ALL if x not in cands]
        rng.shuffle(pool)
        cands += pool[:extra]
    rng.shuffle(cands)
    head = "当前会话可用工具（只能从下列工具中选）：\n" + "\n".join(fmt_tool(c) for c in cands)
    return (base_sys + "\n\n" + head) if base_sys else head, len(cands)


MODES = [m.strip().lower() for m in args.modes.split(",") if m.strip()]
BASE_SYS = G.load_system()
print("=" * 96)
print("RE 三档评测  adapter=%s" % args.adapter)
print("=" * 96)
print("E1 base system %d 字符 · E2 候选 %d 个 · E3 额外干扰 %d 个 · seed %d"
      % (len(BASE_SYS), args.k, args.jitter, args.seed))
print()

model, tok = G.load_model(args.adapter)
res = {}
t_all = time.time()

for mode in MODES:
    hit = noarg = wrong = fake = none = 0
    by_lv = {}
    rows = []
    t0 = time.time()
    for i, c in enumerate(CASES, 1):
        if mode == "e1":
            sys_txt = BASE_SYS
        elif mode == "e2":
            sys_txt, _ = build_system(BASE_SYS, c.get("expect") or [], args.k, seed=args.seed)
        else:  # e3
            sys_txt, _ = build_system(BASE_SYS, c.get("expect") or [], args.k,
                                      extra=args.jitter, seed=args.seed + 1000)
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
        mark = {"hit": "✅", "noarg": "⚠", "wrong": "△", "fake": "❌", "none": "—"}[kind]
        print("  [%s %02d/40] %s %-5s %-4s 得到=%-30s 期望=%s"
              % (mode.upper(), i, mark, c["level"], c["id"],
                 ",".join(sorted(got)) or "无", ",".join(sorted(c["expect"])) or "(负向)"))
        rows.append({"id": c["id"], "level": c["level"], "kind": kind,
                     "got": sorted(got), "fake": sorted(fk), "expect": sorted(c["expect"])})
    r = {"mode": mode, "n": len(CASES), "hit": hit, "noarg": noarg, "wrong": wrong,
         "fake": fake, "none": none, "acc": round(hit / len(CASES), 4),
         "by_level": by_lv, "seconds": round(time.time() - t0, 1), "detail": rows}
    res[mode] = r
    print("  → [%s] %d/40 (%.1f%%) | 参数错 %d | 选错 %d | 编造 %d | 回避 %d  (%.0fs)"
          % (mode.upper(), hit, hit * 100.0 / len(CASES), noarg, wrong, fake, none, r["seconds"]))
    for lv in ("L1", "L2", "L3"):
        d = by_lv.get(lv)
        if d:
            print("      %s %d/%d" % (lv, d["hit"], d["n"]))
    print()

print("=" * 96)
print("汇总与判据")
print("=" * 96)
JUDGE = {"e1": (None, 30, "不许低于 30"), "e2": (36, None, "≥36/40 = 90%"), "e3": (None, None, "相对 E2 掉 ≤2")}
for m, r in res.items():
    print("  %-3s %2d/40 (%.1f%%)  参数错 %d · 选错 %d · 编造 %d · 回避 %d"
          % (m.upper(), r["hit"], r["acc"] * 100, r["noarg"], r["wrong"], r["fake"], r["none"]))
if "e2" in res:
    e2 = res["e2"]["hit"]
    print()
    print("  E2 判据 ≥36 → %s（实际 %d）" % ("✅ 通过" if e2 >= 36 else "❌ 未达", e2))
if "e1" in res:
    print("  E1 判据 ≥30 → %s（实际 %d）" % ("✅ 保持" if res["e1"]["hit"] >= 30 else "❌ 掉了", res["e1"]["hit"]))
if "e2" in res and "e3" in res:
    d = res["e2"]["hit"] - res["e3"]["hit"]
    print("  E3 相对 E2 掉 %d 条 → %s" % (d, "✅ 抗干扰" if d <= 2 else "❌ 干扰敏感"))
allfake = sum(r["fake"] for r in res.values())
print("  编造合计 %d → %s" % (allfake, "✅" if allfake == 0 else "★必须为 0"))

# 结论分级（§5.1b.7 的四种情形）
print()
print("  形态判定：", end="")
if "e1" in res and "e2" in res:
    e1, e2 = res["e1"]["hit"], res["e2"]["hit"]
    if e1 >= 30 and e2 >= 36:
        print("理想 —— 真学会选择且可迁移 → 接 DPO")
    elif e1 < 30 and e2 >= 36:
        print("危险 —— 只会照单选，E1 掉了 %d 条 → 按 §5.1b.7 混 30%% 无候选集样本重训" % (30 - e1))
    elif e1 >= 30 and e2 < 36:
        print("中性 —— 学到一点但不够 → 候选集加硬（更多同簇干扰）或上 DPO")
    else:
        print("失败 —— 方向错 → 回 v4 定稿，转 DPO 路线")
else:
    print("（只跑了部分档，无法判定）")

out = args.out or "train/lines/9b-oxcoder/out/eval-deploy-%s.json" % (
    os.path.basename(os.path.dirname(args.adapter.rstrip("/\\"))))
os.makedirs(os.path.dirname(out), exist_ok=True)
with io.open(out, "w", encoding="utf-8") as f:
    json.dump({"adapter": args.adapter, "base": args.base, "seed": args.seed,
               "k": args.k, "jitter": args.jitter, "results": res}, f,
              ensure_ascii=False, indent=2)
print()
print("  → %s  （总耗时 %.0f s）" % (out, time.time() - t_all))
