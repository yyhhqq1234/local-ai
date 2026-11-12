#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""reabliterate.py —— 训练后再做一次方向消融，主动削弱 residual refusal

原理：abliteration 是沿 refusal direction r 消融。原模型做过一次，但 SFT/LoRA 训练会部分恢复。
本脚本在训练之后再做一次（可叠加多次）：

    W' = W - strength * r (rᵀ W)          # 移除 W 输出中的 r 分量（r 为 hidden 空间的单位向量）

两种作用对象：
    --target weights  直接改 HF 模型的 o_proj / down_proj 权重（激进，影响原始能力）
    --target delta    只改 LoRA 的 B@A 增量（保守，只削训练新引入的倾向）

refusal direction 的来源（二选一）：
    --direction-from-probe  从 compliance_probe.py 的输出 json 读（推荐，省一次前向）
    --estimate               现场跑前向估计（需要 --comply-set / --refuse-set）

用法：
    # 只估方向，不改任何权重
    python reabliterate.py --model <hf_dir> --comply-set comply.jsonl --refuse-set refuse.jsonl \
        --estimate --dry-run --out-dir logs/reabl

    # 用已估好的方向，对完整权重做 70% 强度的消融
    python reabliterate.py --model <hf_dir> --direction logs/reabl/direction.pt \
        --target weights --strength 0.7 --out-dir <clean_dir>

    # 只削 LoRA 增量
    python reabliterate.py --adapter out/adapter --direction logs/reabl/direction.pt \
        --target delta --strength 1.0 --out-dir out/adapter-clean
"""
import argparse
import json
import os
import sys

import torch


def load_direction(path, layer):
    """direction.pt = {layer(int|str): tensor[hidden]}"""
    d = torch.load(path, map_location="cpu", weights_only=True)
    if isinstance(d, dict):
        if layer in d:
            return d[layer].float()
        if str(layer) in d:
            return d[str(layer)].float()
        if "all" in d:
            return d["all"].float()
    raise KeyError(f"direction 文件里没有 layer {layer}（keys={list(d)[:8] if isinstance(d, dict) else type(d)}）")


def normalize(v):
    n = v.norm()
    if n < 1e-8:
        raise ValueError("direction 范数接近 0，估计失败")
    return v / n


# ---------------------------------------------------------------- 估计方向

def estimate_direction(model_dir, comply_path, refuse_path, max_len=512, layers=None):
    """逐层取最后一个 token 的 hidden，算 mean(comply) - mean(refuse) → 单位向量"""
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    print(f"[load] {model_dir}")
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    tok = AutoTokenizer.from_pretrained(model_dir, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_dir, quantization_config=bnb, dtype=torch.bfloat16,
        device_map={"": 0}, trust_remote_code=True)
    model.eval()

    # 找 decoder layers
    core = model
    for attr in ("model",):
        if hasattr(core, attr):
            core = getattr(core, attr)
    if hasattr(core, "language_model"):
        core = core.language_model
    n_layers = len(core.layers)
    want = layers or list(range(n_layers))
    print(f"[layers] {n_layers} 层，采样 {len(want)} 层")

    captured = {}

    def mk_hook(idx):
        def hook(mod, inp, out):
            h = out[0] if isinstance(out, tuple) else out
            if h.dim() == 3:
                captured[idx] = h[0, -1, :].detach().float().cpu()
        return hook

    handles = [core.layers[i].register_forward_hook(mk_hook(i)) for i in want]

    def run_set(path, tag):
        rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
        acc = {i: [] for i in want}
        for r in rows:
            msgs = r.get("messages") or [{"role": "user", "content": r.get("prompt", "")}]
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            ids = tok(text, return_tensors="pt", truncation=True, max_length=max_len).to(model.device)
            captured.clear()
            with torch.no_grad():
                model(**ids)
            for i in want:
                if i in captured:
                    acc[i].append(captured[i])
        out = {}
        for i, vs in acc.items():
            if vs:
                out[i] = torch.stack(vs).mean(0)
        print(f"[{tag}] {len(rows)} 条 → {len(out)} 层向量")
        return out

    comply = run_set(comply_path, "comply")
    refuse = run_set(refuse_path, "refuse")
    for h in handles:
        h.remove()

    direction = {}
    for i in comply:
        if i in refuse:
            v = comply[i] - refuse[i]
            n = v.norm()
            if n > 1e-6:
                direction[i] = (v / n).half()
    print(f"[direction] {len(direction)} 层有效")
    return direction


# ---------------------------------------------------------------- 消融

def ablate_weight(w, r, strength):
    """W: [out, in]，r: [out]（hidden 空间）→ W' = W - s * r (rᵀ W)"""
    if w.shape[0] != r.shape[0]:
        return None
    r = r.to(w.dtype)
    proj = torch.outer(r, r @ w)          # [out, in]
    return w - strength * proj


def clean_hf_weights(model_dir, direction_path, strength, out_dir, which=("o_proj", "down_proj")):
    from safetensors import safe_open
    from safetensors.torch import save_file

    shards = sorted(f for f in os.listdir(model_dir) if f.endswith(".safetensors"))
    os.makedirs(out_dir, exist_ok=True)
    touched = 0
    for sh in shards:
        buf = {}
        with safe_open(os.path.join(model_dir, sh), framework="pt", device="cpu") as f:
            keys = list(f.keys())
            for k in keys:
                buf[k] = f.get_tensor(k)
        for k in list(buf.keys()):
            if not any(t in k for t in which) or not k.endswith(".weight"):
                continue
            # 从 key 里抽层号
            layer = None
            for part in k.split("."):
                if part.isdigit():
                    layer = int(part)
            if layer is None:
                continue
            try:
                r = load_direction(direction_path, layer)
            except KeyError:
                continue
            r = normalize(r)
            new = ablate_weight(buf[k].float(), r, strength)
            if new is not None:
                buf[k] = new.to(buf[k].dtype)
                touched += 1
        save_file(buf, os.path.join(out_dir, sh))
        print(f"[write] {sh}  ({len(buf)} tensors)")
    print(f"[done] 消融 {touched} 个权重矩阵 → {out_dir}")


def clean_lora_delta(adapter_dir, direction_path, strength, out_dir):
    """只削 LoRA 的 B@A 增量：delta' = delta - s·r rᵀ delta，再反解回 A/B（保持秩）"""
    from safetensors import safe_open
    from safetensors.torch import save_file

    src = os.path.join(adapter_dir, "adapter_model.safetensors")
    if not os.path.isfile(src):
        print(f"[FATAL] 缺 {src}")
        sys.exit(2)
    buf = {}
    with safe_open(src, framework="pt", device="cpu") as f:
        for k in f.keys():
            buf[k] = f.get_tensor(k)

    # 配对 lora_A / lora_B
    pairs = {}
    for k in list(buf.keys()):
        if ".lora_A." in k:
            base_k = k.replace(".lora_A.", ".lora_B.")
            if base_k in buf:
                pairs[k] = base_k

    touched = 0
    for ka, kb in pairs.items():
        a = buf[ka].float()          # [r, in]
        b = buf[kb].float()          # [out, r]
        layer = None
        for part in ka.split("."):
            if part.isdigit():
                layer = int(part)
                break
        if layer is None:
            continue
        try:
            r = normalize(load_direction(direction_path, layer))
        except KeyError:
            continue
        if b.shape[0] != r.shape[0]:
            continue
        # delta' = (I - s·r rᵀ) delta  →  等价于把 b 的行投影掉 r 分量
        r_ = r.to(b.dtype)
        b_new = b - strength * torch.outer(r_, r_ @ b)
        buf[ka] = a.to(buf[ka].dtype)
        buf[kb] = b_new.to(buf[kb].dtype)
        touched += 1

    os.makedirs(out_dir, exist_ok=True)
    save_file(buf, os.path.join(out_dir, "adapter_model.safetensors"))
    for extra in ("adapter_config.json",):
        p = os.path.join(adapter_dir, extra)
        if os.path.isfile(p):
            import shutil
            shutil.copy2(p, os.path.join(out_dir, extra))
    print(f"[done] 消融 {touched} 个 LoRA 对 → {out_dir}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="", help="HF 模型目录（--target weights 或估计方向时用）")
    ap.add_argument("--adapter", default="", help="LoRA adapter 目录（--target delta 时用）")
    ap.add_argument("--target", choices=["weights", "delta"], default="delta")
    ap.add_argument("--strength", type=float, default=0.7, help="消融强度 0–1（1=完全移除 r 分量）")
    ap.add_argument("--direction", default="", help="已估计的方向 .pt")
    ap.add_argument("--direction-from-probe", default="", help="compliance_probe 输出 json")
    ap.add_argument("--estimate", action="store_true", help="现场估计方向（需 --comply-set/--refuse-set）")
    ap.add_argument("--comply-set", default="")
    ap.add_argument("--refuse-set", default="")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)

    # 1) 方向来源
    if a.direction_from_probe:
        d = json.load(open(a.direction_from_probe, encoding="utf-8"))
        if "direction_file" not in d:
            print("[FATAL] probe json 里没有 direction_file 字段")
            sys.exit(2)
        a.direction = d["direction_file"]
    if a.estimate:
        if not (a.model and a.comply_set and a.refuse_set):
            print("[FATAL] --estimate 需要 --model / --comply-set / --refuse-set")
            sys.exit(2)
        direction = estimate_direction(a.model, a.comply_set, a.refuse_set)
        p = os.path.join(a.out_dir, "direction.pt")
        torch.save(direction, p)
        print(f"[write] {p}（{len(direction)} 层）")
        if a.dry_run:
            print("[dry-run] 只估方向，未改权重")
            return
        a.direction = p

    if not a.direction:
        print("[FATAL] 需要 --direction / --direction-from-probe / --estimate 之一")
        sys.exit(2)

    if a.dry_run:
        print(f"[dry-run] 将用 {a.direction} 对 --target {a.target} 做 strength={a.strength} 消融，未执行")
        return

    # 2) 消融
    if a.target == "weights":
        if not a.model:
            print("[FATAL] --target weights 需要 --model")
            sys.exit(2)
        clean_hf_weights(a.model, a.direction, a.strength, a.out_dir)
    else:
        if not a.adapter:
            print("[FATAL] --target delta 需要 --adapter")
            sys.exit(2)
        clean_lora_delta(a.adapter, a.direction, a.strength, a.out_dir)


if __name__ == "__main__":
    main()
