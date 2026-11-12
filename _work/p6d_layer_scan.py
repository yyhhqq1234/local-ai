#!/usr/bin/env python
"""P6-D：层敏感性扫描 —— 找出哪些层组影响 GateLeak

背景
    全 Q5 → leak 13.3%（4 条残留露骨词）
    全 Q6 → leak 0.0000，但 recall 掉
    目标：只把「管 leak 的那部分层」升到 Q6，其余保持 Q5，
          在体积和 recall 之间取平衡。

方法
    以全 Q5 为底，逐组把某一类层升到 Q6，生成一个候选模型，
    然后只测 nogate 30 条（最直接反映 leak），看该组的贡献。

分组（按 HF 真实张量名）
    G1 mlp_gate_up       mlp.gate_proj / mlp.up_proj   （原 Q4，32 层 × 2）
    G2 mlp_down          mlp.down_proj                  （原 Q5）
    G3 self_attn         self_attn.q/k/v/o_proj         （full_attention 层，8 层）
    G4 gdn_in            linear_attn.in_proj_qkv/in_proj_z
    G5 gdn_out           linear_attn.out_proj

用法
    python _work/p6d_layer_scan.py --gen-only            # 只生成候选模型
    python _work/p6d_layer_scan.py --group G1            # 生成 G1 候选并测 leak
    python _work/p6d_layer_scan.py --all                 # 全部跑（约 1 h）
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "27b-kittyrev", "quant"))
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
from safetensors import safe_open  # noqa: E402
from safetensors.torch import save_file  # noqa: E402

import gsq_gumbel_v2 as G  # noqa: E402

if "q6_g64_fp16" not in G.FORMATS:
    G.FORMATS["q6_g64_fp16"] = G.Fmt("q6_g64_fp16", 6, 64, -32, 31, code_bias=0)

SRC = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models",
                   "merged-2b-nsfw-mtp-tuned-v3")
CAND_DIR = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models", "_p6d_cand")
PY = os.path.join(ROOT, "train", ".venv", "Scripts", "python.exe")
VAL = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "eval", "val", "nsfw-gate.jsonl")
OUTDIR = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "out")

GROUPS = {
    "G1_mlp_gate_up": lambda n: n.endswith(("mlp.gate_proj.weight", "mlp.up_proj.weight")),
    "G2_mlp_down":    lambda n: n.endswith("mlp.down_proj.weight"),
    "G3_self_attn":   lambda n: n.endswith(("self_attn.q_proj.weight", "self_attn.k_proj.weight",
                                            "self_attn.v_proj.weight", "self_attn.o_proj.weight")),
    "G4_gdn_in":      lambda n: n.endswith(("linear_attn.in_proj_qkv.weight",
                                            "linear_attn.in_proj_z.weight")),
    "G5_gdn_out":     lambda n: n.endswith("linear_attn.out_proj.weight"),
}

KEEP_FP = ("norm", "a_log", "dt_bias", "convolution", "a_projection", "b_projection")


def base_fmt(name: str):
    """全 Q5 基线下的格式（vocab q8，其余 2D 投影 q5，非投影不量化）"""
    low = name.lower()
    if "embed_tokens" in low or "lm_head" in low:
        return "q8_g32_fp16"
    if any(k in low for k in KEEP_FP) or low.startswith("mtp."):
        return None
    if not low.endswith(".weight"):
        return None
    if low.endswith(("q_proj.weight", "k_proj.weight", "gate_proj.weight", "up_proj.weight",
                     "v_proj.weight", "o_proj.weight", "down_proj.weight",
                     "in_proj_qkv.weight", "in_proj_z.weight", "out_proj.weight")):
        return "q5_g64_fp16"
    return None


def build_candidate(group_name: str, promote_fmt: str = "q6_g64_fp16"):
    """以全 Q5 为底，把指定组升到 promote_fmt"""
    pred = GROUPS[group_name]
    dst = os.path.join(CAND_DIR, group_name)
    os.makedirs(dst, exist_ok=True)
    dst_file = os.path.join(dst, "model.safetensors")
    if os.path.exists(dst_file):
        print(f"[skip] {group_name} 已存在")
        return dst

    src_file = os.path.join(SRC, "model.safetensors")
    out = {}
    n_up = 0
    t0 = time.time()
    with safe_open(src_file, "pt", device="cpu") as f:
        for k in f.keys():
            w = f.get_tensor(k)
            fmt = base_fmt(k)
            shp = tuple(w.shape)
            if fmt is None or len(shp) != 2 or min(shp) < 64:
                out[k] = w
            else:
                if pred(k):
                    fmt = promote_fmt
                    n_up += 1
                wf = w.float()
                qm = G.baseline_absmax(wf, fmt)
                w_hat = G.dequantize(qm, fmt, k=shp[1])
                out[k] = w_hat.to(torch.bfloat16).reshape(shp).contiguous()
                del wf, qm, w_hat
            del w
    save_file(out, dst_file, metadata={"format": "pt"})
    for fn in ("config.json", "generation_config.json", "chat_template.jinja",
               "tokenizer.json", "tokenizer_config.json",
               "preprocessor_config.json", "processor_config.json"):
        s = os.path.join(SRC, fn)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(dst, fn))
    print(f"[build] {group_name}: 升级 {n_up} 个张量到 {promote_fmt} · {time.time()-t0:.1f}s")
    return dst


def run_leak_test(model_dir: str, group_name: str):
    """只跑 nogate 30 条，测 leak"""
    out_json = os.path.join(OUTDIR, f"p6d-{group_name}-leak.json")
    log = os.path.join(ROOT, "train", "logs", f"p6d-{group_name}.log")
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "VRAM_FRAC": "0.85", "HF_HUB_OFFLINE": "1"})
    # 用 p6b_eval 的全量（85 条太慢），这里改跑 limit 前 30 条不够对；
    # 直接跑全量但 max-new 减半，靠 nogate 段落取指标
    cmd = [PY, os.path.join(ROOT, "_work", "p6b_eval.py"),
           "--model", model_dir, "--max-new", "1024",
           "--kinds", "nogate", "--out", out_json]
    print(f"[test] {group_name} → {out_json}")
    with open(log, "w", encoding="utf-8") as fh:
        rc = subprocess.call(cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT)
    if rc != 0:
        print(f"[FAIL] {group_name} rc={rc}，见 {log}")
        return None
    d = json.load(open(out_json, encoding="utf-8"))
    leak_rows = [r for r in d["rows"] if r["kind"] == "nogate" and r["nsfw"]]
    return {"group": group_name, "gate_leak": d["gate_leak"],
            "gate_recall": d["gate_recall"],
            "leak_ids": [r["id"] for r in leak_rows],
            "n_leak": len(leak_rows)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--gen-only", action="store_true")
    ap.add_argument("--keep", action="store_true", help="测完保留候选模型（默认删，磁盘紧张）")
    a = ap.parse_args()

    os.makedirs(CAND_DIR, exist_ok=True)
    groups = list(GROUPS) if (a.all or not a.group) else [a.group]

    if a.gen_only:
        for g in groups:
            build_candidate(g)
        return

    results = []
    for g in groups:
        d = build_candidate(g)
        r = run_leak_test(d, g)
        if r:
            results.append(r)
            print(f"[result] {g}: leak={r['gate_leak']:.4f} "
                  f"recall={r['gate_recall']:.4f} 漏条={r['leak_ids']}")
        # ★ 磁盘只有 28 GB（96%），每个候选 18 GB 装不下两个
        #   测完立刻删，串行推进
        if not a.keep:
            import shutil as _sh
            _sh.rmtree(d, ignore_errors=True)
            print(f"[clean] 已删 {d}")

    if results:
        p = os.path.join(OUTDIR, "p6d-layer-scan.json")
        json.dump(results, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"\n[OK] → {p}")


if __name__ == "__main__":
    main()
