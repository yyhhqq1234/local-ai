#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""plan_layers.py —— 把探针结果翻译成训练配置（§14.4 决策树的代码化）

输入（probe_layers.py 的四份产物）：
    probe_by_cat.json        {cat: {layer: acc}}  或 {cat: {layer: delta_loss}}
    probe_acc.json           {label: {layer: acc}}（总体曲线，用于兜底）
    adapter_layer_norm.json  {layer: {"A_fro":.., "B_fro":.., "BA_spec":..}}
    logit_lens.json          {layer: convergence_layer}

输出：
    plan.json                层段 / rank / 数据配比 / 预估显存 / 生成的命令
    并在 stdout 打印可复制的 PowerShell 命令

用法：
    python plan_layers.py --probe-dir logs/probe --out train/lines/27b-kittyrev/kitty-rev/logs/plan.json
    python plan_layers.py --probe-dir logs/probe --dry-run    # 只看推荐，不写文件
"""
import argparse
import json
import os
import sys

# 本机 12 GB 的可训层上限：层权重 4bit ≈189 MiB/层 + head 2.37 GiB + 激活 1.2 GiB
VRAM_BUDGET_GIB = 10.0
GIB = 1024 ** 3
PER_LAYER_4BIT_GIB = 189 / 1024          # 实测单层 4bit
HEAD_GIB = 2.37
ACT_GIB = 1.2

# 类别清单在 CAT_TO_DIR 定义之后派生（见下）：新增类别只要登记映射，
# 就不会出现「映射了但决策树不看」。这里只是占位，避免前向引用。
CATS = []

# --------------------------------------------------------------------------- #
# act-cache layout produced by precompute_activations.py --split-by-subsets.
# The source name in --data-mix MUST equal the act-cache subdirectory name
# verbatim (`re-train`, not `re`), otherwise MultiCache raises
# "[FATAL] 源 re 下没有 *.pt" before the first training step.
# --------------------------------------------------------------------------- #
ACT_ROOT = "train/lines/27b-kittyrev/local-pack/act-cache"      # forward slashes: safe in bash and PowerShell
CAT_TO_DIR = {
    "kb-re": "re-train",
    "action-reverse": "re-train",            # SAME directory as kb-re -> must merge
    "tool-route": "route-train",
    "op-syntax": "route-train",
    "real-discipline": "discipline-train",
    # comply-*: 配合意愿（下一轮配比 comply:3, forge:4, re-train:2, rest:1）。
    # 登记后 CATS 自动含它们（决策树"看得见"）；但**不会被自动加权** ——
    # 决策树里的 cats_to_mix({...}) 是硬编码调用点，下一轮要用时必须在 seg() 里显式加。
    "comply-a": "comply-train",
    "comply-b": "comply-train",
    "comply-c": "comply-train",
    "comply-d": "comply-train",
}
CATS = list(CAT_TO_DIR)                      # 单一真相源：类别 = 映射表的键
# Replay pool: rest/ has 2774 rows; gen-train has only 80, so a 4:1 mix on
# gen-train would resample the same 80 rows 3-4x per epoch = overfit on 80.
REPLAY_TRAIN_DIR = "rest"
REPLAY_VAL_DIR = "gen-val"                   # 20 rows, independent -> enough for early stop


def cats_to_mix(cat_weights, unknown=None):
    """{'kb-re':3,'action-reverse':1} -> {'re-train':4}   (weights summed).

    Two categories share one act-cache directory; emitting them as two sources
    with the same name would collide inside MultiCache.

    未知类别过去静默落 `rest` —— 双重错：新类别的权重被并进**回放池**，
    而 `rest` 一进 mix，build_mix() 就不再追加回放项，回放权重无声变 0。
    新数据组（forge-*）必须先登记 CAT_TO_DIR；没登记就明说，不要猜。
    """
    out, bad = {}, []
    for cat, w in cat_weights.items():
        if cat not in CAT_TO_DIR:
            bad.append(cat)
            continue
        d = CAT_TO_DIR[cat]
        out[d] = out.get(d, 0.0) + float(w)
    if bad:
        if unknown is not None:
            unknown.extend(bad)
        else:
            raise SystemExit(
                f"[FATAL] 未知类别 {bad}：不在 CAT_TO_DIR 里。新增数据组（如 forge-*）"
                f"必须先登记它的 act-cache 子目录，否则权重会静默并进 rest（回放池）"
                f"并把回放权重清零。已知类别：{sorted(CAT_TO_DIR)}")
    return out


def build_mix(mix, replay_weight=1.0, root=None):
    """{'re-train':4} -> 're-train:<root>/re-train:4,rest:<root>/rest:1'"""
    root = root or ACT_ROOT
    parts = [f"{src}:{root}/{src}:{w:g}" for src, w in mix.items()]
    if REPLAY_TRAIN_DIR in mix:
        print(f"[mix][warn] {REPLAY_TRAIN_DIR} 已在 mix 里（权重 {mix[REPLAY_TRAIN_DIR]:g}）："
              f"按显式权重走，额外回放项被跳过")
    elif replay_weight:
        parts.append(f"{REPLAY_TRAIN_DIR}:{root}/{REPLAY_TRAIN_DIR}:{replay_weight:g}")
    return ",".join(parts)


def build_val(extra_dirs=(), root=None, with_forge=False):
    """Val sources: the segment's own val dirs + forge-val (if forge is in play)
    + the shared replay val dir.

    forge-val pairs with forge-train by FAMILY (directory name minus -train/-val
    -> `forge`), so the two source names do NOT need to match.
    """
    root = root or ACT_ROOT
    dirs = list(extra_dirs)
    if with_forge and "forge-val" not in dirs:
        dirs.append("forge-val")
    if REPLAY_VAL_DIR not in dirs:
        dirs.append(REPLAY_VAL_DIR)
    return ",".join(f"{d}:{root}/{d}" for d in dirs)


def load_json(p):
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# shape adapters
#   plan_layers originally expected flat maps ({cat: {layer: score}}), but
#   probe_layers.py writes envelopes ({cats: {cat: {probe_by_layer: ...}},
#   ablation_dloss: ...}, {curves: ...}, {layers: ...}) so that one file can
#   carry metadata next to the numbers.  Normalising here keeps both ends
#   honest instead of silently producing an empty plan.
# --------------------------------------------------------------------------- #
def norm_by_cat(d):
    if not d:
        return {}
    if "cats" in d:
        out = {}
        for cat, rec in (d.get("cats") or {}).items():
            curve = rec.get("probe_by_layer") or {}
            if not curve:
                curve = (d.get("ablation_dloss") or {}).get(cat) or {}
            if curve:
                out[cat] = curve
        for cat, dl in (d.get("ablation_dloss") or {}).items():
            out.setdefault(cat, dl)
        return out
    return {k: v for k, v in d.items() if isinstance(v, dict)}


def norm_overall(d):
    if not d:
        return {}
    return d.get("curves", d)


def norm_adapter(d):
    if not d:
        return {}
    return d.get("layers", d)


def norm_lens(d):
    if not d:
        return {}
    if "convergence_layer" not in d and "convergence_median" in d:
        d = dict(d)
        d["convergence_layer"] = d["convergence_median"]
    return d


def span_of(curve, thresh=None):
    """curve: {layer(int|str): score} → (start, end, peak, mean, sigma)"""
    pts = {int(k): float(v) for k, v in curve.items() if v is not None}
    if not pts:
        return None
    layers = sorted(pts)
    vals = [pts[l] for l in layers]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    sigma = var ** 0.5
    peak = max(pts, key=lambda l: pts[l])
    if thresh is None:
        thresh = mean + sigma
    hot = [l for l in layers if pts[l] >= thresh]
    if not hot:
        return (peak, peak, peak, mean, sigma)
    return (min(hot), max(hot), peak, mean, sigma)


def memory_estimate(n_layers):
    return PER_LAYER_4BIT_GIB * n_layers + HEAD_GIB + ACT_GIB


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-dir", required=True)
    ap.add_argument("--out", default="")
    ap.add_argument("--act-root", default=ACT_ROOT,
                    help=f"act-cache 根目录（默认 {ACT_ROOT}）")
    ap.add_argument("--forge", choices=["auto", "on", "off"], default="auto",
                    help="是否把 forge-train 作为独立源（auto=该目录存在则用，配比 forge:4 + re-train:2）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    act_root = a.act_root
    if a.forge == "on":
        use_forge = True
    elif a.forge == "off":
        use_forge = False
    else:
        use_forge = os.path.isdir(os.path.join(act_root, "forge-train"))
    print(f"[act] root={act_root}  forge={'on' if use_forge else 'off'}"
          f"{'（auto 探测到 forge-train/）' if a.forge == 'auto' and use_forge else ''}")

    by_cat = norm_by_cat(load_json(os.path.join(a.probe_dir, "probe_by_cat.json")))
    overall = norm_overall(load_json(os.path.join(a.probe_dir, "probe_acc.json")))
    adapter = norm_adapter(load_json(os.path.join(a.probe_dir, "adapter_layer_norm.json")))
    lens = norm_lens(load_json(os.path.join(a.probe_dir, "logit_lens.json")))

    if not by_cat and not adapter:
        print("[FATAL] probe_by_cat.json 与 adapter_layer_norm.json 都缺，无法决策")
        sys.exit(2)

    unknown_cats = sorted(set(by_cat) - set(CAT_TO_DIR))
    if unknown_cats:
        print(f"[warn] probe_by_cat.json 里有未登记的类别 {unknown_cats}："
              f"它们不进决策树、也不分配权重（先登记 CAT_TO_DIR 再跑）")
    # 反向：该有的类别没数据（probe 侧 <8 条被 skip、或全被弱标签过滤），
    # 决策树就静默少看这一类，而兜底分支的 note 写「峰不分离」—— 归因错了。
    missing_cats = [c for c in CAT_TO_DIR if by_cat and c not in by_cat]
    if missing_cats:
        print(f"[warn] 期望类别在 probe_by_cat.json 里缺失 {missing_cats}："
              f"这些类没有探针数据，本计划不含它们（不是峰不分离的问题）")
    report = {"inputs": {"by_cat": bool(by_cat), "overall": bool(overall),
                         "adapter": bool(adapter), "logit_lens": bool(lens)},
              "unknown_cats": unknown_cats,
              "missing_cats": missing_cats,
              "spans": {}, "adapter_peak": None, "convergence_layer": None}

    # 1) 每类的敏感层段
    spans = {}
    for cat in CATS:
        if by_cat and cat in by_cat:
            s = span_of(by_cat[cat])
            if s:
                spans[cat] = {"start": s[0], "end": s[1], "peak": s[2],
                              "mean": round(s[3], 4), "sigma": round(s[4], 4)}
    report["spans"] = spans

    # 2) adapter 能量峰（最硬证据）
    if adapter:
        key = "BA_spec" if any("BA_spec" in v for v in adapter.values() if isinstance(v, dict)) else "B_fro"
        curve = {l: (v.get(key) if isinstance(v, dict) else v) for l, v in adapter.items()}
        s = span_of(curve)
        if s:
            report["adapter_peak"] = {"peak": s[2], "start": s[0], "end": s[1]}

    # 3) logit lens 收敛层
    if lens:
        conv = lens.get("convergence_layer") or lens.get("convergence")
        if isinstance(conv, int):
            report["convergence_layer"] = conv

    # 4) 决策树（§14.4）
    re_span = spans.get("kb-re") or spans.get("action-reverse")
    route_span = spans.get("tool-route")
    dis_span = spans.get("real-discipline")
    plan = {"segments": [], "note": "", "strategy": ""}

    def seg(name, start, end, rank, mix, val_dirs, steps):
        """mix: {act_cache_subdir: weight}; val_dirs: [act_cache val subdirs]."""
        n = end - start + 1
        return {"name": name, "from": start, "to": end, "lora_r": rank,
                "mix": mix, "val_dirs": val_dirs, "max_steps": steps,
                "data_mix": build_mix(mix, root=act_root),
                "val_cache": build_val(val_dirs, root=act_root, with_forge=use_forge),
                "vram_gib": round(memory_estimate(n), 2),
                "ok": memory_estimate(n) <= VRAM_BUDGET_GIB}

    # 裁决 A 的配比：forge 是独立池（re/route/discipline 已剔除 forge 行），
    # 所以 "forge:4, re-train:2" 的语义就是「forge 4 倍、旧 re 2 倍」，
    # 不会有某 60 条被双计成 6 倍。
    re_mix = {"forge-train": 4, "re-train": 2} if use_forge else {"re-train": 4}

    # Weights are expressed over CATEGORIES and then folded onto act-cache
    # directories with cats_to_mix(), so kb-re + action-reverse never become two
    # sources pointing at the same `re-train` directory.
    if re_span and route_span and abs(re_span["peak"] - route_span["peak"]) >= 8:
        plan["strategy"] = "peak-separated"
        plan["note"] = "三类能力峰分离，按段训专用 LoRA（§14.4 情况一）"
        plan["segments"] = [
            seg("A_re", max(0, re_span["peak"] - 4), min(63, re_span["peak"] + 4), 32,
                dict(re_mix), ["re-val"], 120),
            seg("B_route", max(0, route_span["peak"] - 4), min(63, route_span["peak"] + 4), 16,
                cats_to_mix({"tool-route": 2}), ["route-val"], 80),
            seg("C_close", 56, 63, 8,
                cats_to_mix({"real-discipline": 1}), ["discipline-val"], 60),
        ]
    elif re_span and route_span and re_span["peak"] >= 44 and route_span["peak"] >= 44:
        plan["strategy"] = "concentrated-tail"
        plan["note"] = "逆向与路由都集中后段 → 单段 48–63，靠数据加权补偿（§14.4 情况三，最常见）"
        plan["segments"] = [
            seg("A_re_weighted", 48, 63, 16, dict(re_mix), ["re-val"], 160),
        ]
    else:
        plan["strategy"] = "merged-or-unknown"
        plan["note"] = "峰不分离且不在后段 → 先按 32–63 试，或降级为格式对齐（§14.4 情况二/四）"
        plan["segments"] = [
            seg("A_wide", 32, 63, 16,
                {**re_mix, **cats_to_mix({"tool-route": 2})},
                ["re-val", "route-val"], 140),
        ]

    # 5) 显存闸门检查
    over = [s for s in plan["segments"] if not s["ok"]]
    if over:
        plan["warning"] = [f"{s['name']} 预估 {s['vram_gib']} GiB > {VRAM_BUDGET_GIB} GiB，需 --ce-chunk 64 或缩层段"
                           for s in over]

    if missing_cats:
        plan["note"] += f"（注意：{missing_cats} 没有探针数据，本结论不含它们）"
    report["plan"] = plan

    # 6) 生成命令（复制即可跑：源名 = act-cache 子目录名，回放走 rest/）
    cmds = []
    for s in plan["segments"]:
        cmds.append(
            "& train\\.venv\\Scripts\\python.exe train\\kitty-rev\\scripts\\train_partial_lora.py `\n"
            f"    --layer-dir train/lines/27b-kittyrev/local-pack/merged-layers --from {s['from']} --to {s['to']} `\n"
            f"    --head train/lines/27b-kittyrev/local-pack/merged-layers/head.safetensors `\n"
            f"    --data-mix \"{s['data_mix']}\" `\n"
            f"    --eval-cache \"{s['val_cache']}\" `\n"
            f"    --ctx 512 --lora-r {s['lora_r']} --bs 1 --ga 8 --max-steps {s['max_steps']} `\n"
            f"    --dtype 4bit --max-vram-gb {VRAM_BUDGET_GIB} --eval-by-cat `\n"
            f"    --out train/lines/27b-kittyrev/kitty-rev/out-{s['name']}"
        )
    report["commands"] = cmds
    report["optional_refusal_args"] = (
        f"--refusal-cache \"comply:{ACT_ROOT}/comply\" "
        f"--refusal-directions train/lines/27b-kittyrev/local-pack/refusal.direction.pt")

    print("=" * 70)
    print(f"strategy : {plan['strategy']}")
    print(f"note     : {plan['note']}")
    print(f"adapter peak layer : {report['adapter_peak']}")
    print(f"convergence layer  : {report['convergence_layer']}")
    print("-" * 70)
    for cat, s in spans.items():
        print(f"  {cat:18s} span {s['start']:2d}-{s['end']:2d}  peak {s['peak']:2d}  (mean {s['mean']}, σ {s['sigma']})")
    print("-" * 70)
    for s in plan["segments"]:
        flag = "OK " if s["ok"] else "OVER"
        mixs = " + ".join(f"{k}:{v:g}" for k, v in s["mix"].items())
        print(f"  [{flag}] {s['name']:16s} layers {s['from']}-{s['to']}  r={s['lora_r']}  "
              f"steps={s['max_steps']}  vram≈{s['vram_gib']} GiB")
        print(f"         数据 {mixs} + {REPLAY_TRAIN_DIR}:1   val {', '.join(s['val_dirs'] + [REPLAY_VAL_DIR])}")
    if plan.get("warning"):
        for w in plan["warning"]:
            print(f"  [WARN] {w}")
    print("=" * 70)
    for i, c in enumerate(cmds, 1):
        print(f"\n--- command {i} ---\n{c}\n")
    print(f"[可选] 另需 abliteration 探针时，在命令末尾追加：\n  {report['optional_refusal_args']}")

    if a.dry_run:
        print("[dry-run] 未写文件")
        return
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"[write] {a.out}")


if __name__ == "__main__":
    main()
