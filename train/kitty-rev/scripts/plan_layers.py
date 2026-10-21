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
    python plan_layers.py --probe-dir logs/probe --out train/kitty-rev/logs/plan.json
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

CATS = ["kb-re", "action-reverse", "tool-route", "op-syntax", "real-discipline"]


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
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    by_cat = norm_by_cat(load_json(os.path.join(a.probe_dir, "probe_by_cat.json")))
    overall = norm_overall(load_json(os.path.join(a.probe_dir, "probe_acc.json")))
    adapter = norm_adapter(load_json(os.path.join(a.probe_dir, "adapter_layer_norm.json")))
    lens = norm_lens(load_json(os.path.join(a.probe_dir, "logit_lens.json")))

    if not by_cat and not adapter:
        print("[FATAL] probe_by_cat.json 与 adapter_layer_norm.json 都缺，无法决策")
        sys.exit(2)

    report = {"inputs": {"by_cat": bool(by_cat), "overall": bool(overall),
                         "adapter": bool(adapter), "logit_lens": bool(lens)},
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

    def seg(name, start, end, rank, data, steps):
        n = end - start + 1
        return {"name": name, "from": start, "to": end, "lora_r": rank,
                "data": data, "max_steps": steps,
                "vram_gib": round(memory_estimate(n), 2),
                "ok": memory_estimate(n) <= VRAM_BUDGET_GIB}

    if re_span and route_span and abs(re_span["peak"] - route_span["peak"]) >= 8:
        plan["strategy"] = "peak-separated"
        plan["note"] = "三类能力峰分离，按段训专用 LoRA（§14.4 情况一）"
        plan["segments"] = [
            seg("A_re", max(0, re_span["peak"] - 4), min(63, re_span["peak"] + 4), 32, "re-subset.jsonl", 120),
            seg("B_route", max(0, route_span["peak"] - 4), min(63, route_span["peak"] + 4), 16, "route-subset.jsonl", 80),
            seg("C_close", 56, 63, 8, "discipline-subset.jsonl", 60),
        ]
    elif re_span and route_span and re_span["peak"] >= 44 and route_span["peak"] >= 44:
        plan["strategy"] = "concentrated-tail"
        plan["note"] = "逆向与路由都集中后段 → 单段 48–63，靠数据加权补偿（§14.4 情况三，最常见）"
        plan["segments"] = [
            seg("A_re_weighted", 48, 63, 16, "re-subset.jsonl x3 + route x2 + discipline x1", 160),
        ]
    else:
        plan["strategy"] = "merged-or-unknown"
        plan["note"] = "峰不分离且不在后段 → 先按 32–63 试，或降级为格式对齐（§14.4 情况二/四）"
        plan["segments"] = [
            seg("A_wide", 32, 63, 16, "re x3 + route x2 + discipline x1", 140),
        ]

    # 5) 显存闸门检查
    over = [s for s in plan["segments"] if not s["ok"]]
    if over:
        plan["warning"] = [f"{s['name']} 预估 {s['vram_gib']} GiB > {VRAM_BUDGET_GIB} GiB，需 --ce-chunk 64 或缩层段"
                           for s in over]

    report["plan"] = plan

    # 6) 生成命令
    cmds = []
    for s in plan["segments"]:
        cmds.append(
            "& train\\.venv\\Scripts\\python.exe train\\kitty-rev\\scripts\\train_partial_lora.py `\n"
            f"    --layer-dir train\\local-pack\\merged-layers --from {s['from']} --to {s['to']} `\n"
            f"    --head train\\local-pack\\merged-layers\\head.safetensors `\n"
            f"    --act-cache train\\local-pack\\act-cache --ctx 512 --lora-r {s['lora_r']} `\n"
            f"    --data-mix \"{s['data']}\" --bs 1 --ga 8 --max-steps {s['max_steps']} `\n"
            f"    --dtype 4bit --max-vram-gb {VRAM_BUDGET_GIB} --eval-by-cat `\n"
            f"    --out train\\kitty-rev\\out-{s['name']}"
        )
    report["commands"] = cmds

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
        print(f"  [{flag}] {s['name']:16s} layers {s['from']}-{s['to']}  r={s['lora_r']}  "
              f"steps={s['max_steps']}  vram≈{s['vram_gib']} GiB")
    if plan.get("warning"):
        for w in plan["warning"]:
            print(f"  [WARN] {w}")
    print("=" * 70)
    for i, c in enumerate(cmds, 1):
        print(f"\n--- command {i} ---\n{c}\n")

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
