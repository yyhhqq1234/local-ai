#!/usr/bin/env python
"""sra_abliterate.py — Surgical Refusal Ablation（概念引导谱残差化）实现。

论文：arXiv 2601.08489 "Surgical Refusal Ablation: Disentangling Safety from
Intelligence via Concept-Guided Spectral Cleaning"（Cristofano, 2026-01）

与 Heretic/ARA 的区别：
  ARA     直接对「脏拒绝向量」做任意秩消融 → KL 0.5-2.0（能力受损可见）
  SRA     先把脏向量对「能力/风格原子」做岭回归残差化，只消融纯拒绝分量
          → 论文实测 KL 0.016-0.044，同拒率，GSM8K/MBPP 困惑度几乎不变

本实现的三段：
  ① collect   4bit 模型 GPU 前向，hook 每层 decoder input 残差，求数据集均值
  ② residualize   r_clean = r_dirty − A_SC · ŵ ，ridge 最小二乘
  ③ apply     W ← (I − γ v vᵀ) W 对 down_proj / o_proj，safetensors 流式分片写出

用法：
  # 先小规模验证（推荐）
  train/.venv/Scripts/python.exe train/scripts/sra_abliterate.py \
      --model   train/models/OxCoder-9B \
      --out     train/models/OxCoder-9B-sra \
      --layers  6-24 --gamma 1.0 --passes 2 --limit 60 --dry-run

  # 正式
  ... --limit 0 --passes 3 --gamma 1.2
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import shutil
import sys

import torch
import torch.nn.functional as F

JoblibHint = None  # 占位，避免误 import

# ────────────────────────────────────────────────────────────────────────────
# 概念原子（Contrastive prompt pairs）
# 论文要求每个原子 10-15 对，且用独立数据集（不与拒绝集重叠）
# Shields = 必须保护的能力；Confounds = 与拒绝模板共现的风格噪声
# ────────────────────────────────────────────────────────────────────────────
ATOMS: dict[str, tuple[list[str], list[str]]] = {
    "coding": (
        [
            "Write a Python function that reverses a singly linked list.",
            "Implement quicksort in C and explain the pivot choice.",
            "Fix the bug in this loop: for i in range(len(xs)): xs[i + 1] += 1",
            "Explain what a binary search tree is and where it degrades to O(n).",
            "Write a SQL query joining orders and customers on customer_id.",
            "What does a segfault in C usually indicate?",
            "Show how to handle exceptions in Rust with Result.",
            "Write a regex that matches ISO-8601 dates.",
            "Compare a mutex and a semaphore with a short code example.",
            "Explain the difference between a stack and a heap allocation.",
            "Write a bash one-liner that counts unique lines in a file.",
            "How do you profile a slow Python function?",
        ],
        [
            "Describe the colour of the sky at noon.",
            "Tell me about the history of tea in China.",
            "What is a comfortable room temperature?",
            "Summarise the plot of a well known novel.",
            "Which vegetables grow well in spring?",
            "Describe how a mountain range forms over time.",
            "What are common spices in Mediterranean cooking?",
            "Talk about the migration of birds in autumn.",
            "Describe the sound of rain on a tin roof.",
            "What makes a good cup of coffee?",
            "Explain why leaves change colour.",
            "Describe a quiet street in the early morning.",
        ],
    ),
    "math": (
        [
            "Compute 17 * 23 and show the intermediate steps.",
            "Solve for x: 3x + 7 = 25.",
            "What is the derivative of x^3 sin(x)?",
            "Integrate 1/(1+x^2) dx.",
            "A train travels 120 km in 1.5 hours; what is its average speed?",
            "Find the eigenvalues of [[2,1],[1,2]].",
            "What is the probability of two heads in three fair coin flips?",
            "Simplify (a+b)^2 - (a-b)^2.",
            "Convert 45 degrees to radians and give the sine.",
            "Compute the sum of the first 100 positive integers.",
            "What is the determinant of a 3x3 identity matrix?",
            "Solve the recurrence T(n) = 2T(n/2) + n.",
        ],
        [
            "Describe the smell of fresh bread.",
            "What are the main colours in a sunset?",
            "Talk about how cities grew along rivers.",
            "Describe the texture of silk.",
            "What is a common greeting in Portugal?",
            "Describe the shape of a cumulus cloud.",
            "Which instruments are in a string quartet?",
            "Describe the taste of ripe mango.",
            "How does one brew green tea?",
            "Describe the feeling of cold wind.",
            "What plants suit a shaded garden?",
            "Describe the sound of a distant train.",
        ],
    ),
    "logic": (
        [
            "All mammals are warm blooded. A dolphin is a mammal. What follows?",
            "If it rains the ground is wet. The ground is dry. What can you infer?",
            "No reptiles have fur. A gecko is a reptile. Can it have fur?",
            "Either the switch is off or the lamp is broken. The lamp works. What holds?",
            "If A implies B and B implies C, and A is true, is C true?",
            "Some birds cannot fly. A penguin is a bird. Must it fly?",
            "All primes above 2 are odd. 9 is odd. Is 9 prime? Explain the gap.",
            "If no student passed, and Ana is a student, what do we know?",
            "Only members may vote. Kim voted. What can be concluded?",
            "If x > y and y > z, how do x and z relate?",
            "Every even number is divisible by two. 14 is even. Conclude.",
            "If the store is closed on Sunday, and today it is open, what follows?",
        ],
        [
            "Describe a busy market in the morning.",
            "What is your favourite kind of music?",
            "Describe the smell of pine forest.",
            "Tell me about the history of the bicycle.",
            "What makes bread rise?",
            "Describe a typical breakfast in Japan.",
            "How do you keep houseplants healthy?",
            "Describe the sound of waves on a beach.",
            "What colours appear in an autumn forest?",
            "Describe how to fold a paper crane.",
            "Talk about the appeal of old films.",
            "Describe the taste of black pepper.",
        ],
    ),
    # ── Shield：本项目定制，直接保护「逆向/系统分析」能力方向 ───────────
    # 通用 abliteration 只保护 logic/math/coding，但我们的目标是保 RE，
    # 所以显式给逆向分析建一个原子，让 r_clean 对它正交。
    "reverse_analysis": (
        [
            "Disassemble this function and explain what the loop computes.",
            "How do I find the license check in a stripped PE binary?",
            "Trace the calling convention used at this stack frame.",
            "Identify the anti-debug checks in this binary.",
            "Recover the struct layout from these memory accesses.",
            "Find the pointer chain from the module base to this field.",
            "What does this decompiled pseudocode do with the return value?",
            "Explain how to locate the string decryption routine.",
            "Compare the two builds at byte level and find the changed branch.",
            "Describe how to dump an unpacked image and rebuild its sections.",
            "What breakpoint do I set to catch the file open call?",
            "Read this network capture and reconstruct the session framing.",
        ],
        [
            "Recommend a good pasta recipe.",
            "Describe the architecture of a medieval castle.",
            "What are the benefits of morning walks?",
            "Tell me about the migration patterns of whales.",
            "Describe how to care for a bonsai tree.",
            "What makes a violin sound warm?",
            "Describe the layout of a traditional Japanese garden.",
            "Which fabrics are best for winter coats?",
            "Describe a typical day in a small fishing village.",
            "What spices go into a good curry?",
            "Describe the light in a forest at dawn.",
            "Talk about the appeal of handwritten letters.",
        ],
    ),
    # ── Confound：拒绝模板的自有风格（否定/免责/施压语气）──────────────
    "refusal_grammar": (
        [
            "I cannot help with that request.",
            "I'm sorry, but I am unable to assist with this.",
            "That is not something I can provide.",
            "I must decline to answer this question.",
            "As an AI I am not permitted to do that.",
            "I won't be able to comply with that instruction.",
            "Unfortunately I cannot fulfil this request.",
            "I am not able to share that information.",
            "It would be inappropriate for me to help here.",
            "I cannot and will not produce that content.",
            "This request falls outside what I can support.",
            "I have to refuse this one.",
        ],
        [
            "Here is the information you asked for.",
            "Sure, let me walk through it.",
            "The answer is straightforward.",
            "Below is a short explanation.",
            "Yes, that can be done as follows.",
            "Here are the steps involved.",
            "This works as described.",
            "Let me show the result directly.",
            "The details are as follows.",
            "That is correct, and here is why.",
            "I can confirm this point.",
            "Here is the completed output.",
        ],
    ),
}


def parse_layers(spec: str, n_layers: int) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        lo, hi = int(a), int(b)
    else:
        lo = hi = int(spec)
    lo = max(0, lo)
    hi = min(n_layers - 1, hi)
    return list(range(lo, hi + 1))


def load_tokens(tok, texts: list[str], max_len: int) -> list[torch.Tensor]:
    out = []
    for t in texts:
        ids = tok(t, return_tensors="pt", truncation=True, max_length=max_len)["input_ids"]
        out.append(ids)
    return out


def mean_residual(layers, tok_texts, max_len: int, device: str) -> dict[int, torch.Tensor]:
    """前向一遍，返回 {layer_idx: mean over prompts of last-token residual} (float32, CPU)"""
    acc: dict[int, torch.Tensor] = {}
    handles = []

    def make_hook(idx):
        def fn(module, args, kwargs):
            hs = args[0] if args else kwargs.get("hidden_states")
            if hs is None:
                return
            # 取这条样本最后一个 token 的残差（batch 内逐条处理，batch_size=1）
            vec = hs[0, -1, :].detach().float().cpu()
            if idx in acc:
                acc[idx] += vec
            else:
                acc[idx] = vec.clone()
        return fn

    for idx, layer in enumerate(layers):
        handles.append(layer.register_forward_pre_hook(make_hook(idx), with_kwargs=True))
    try:
        for ids in tok_texts:
            ids = ids.to(device)
            with torch.no_grad():
                layers[0].__class__  # noqa: B018  (touch)
                model_out = _FORWARD(ids)
            del model_out
    finally:
        for h in handles:
            h.remove()

    n = max(len(tok_texts), 1)
    return {k: (v / n).cpu() for k, v in acc.items()}


_FORWARD = None  # 由主流程注入


def ridge_residualize(r: torch.Tensor, A: torch.Tensor, lam: float) -> torch.Tensor:
    """r_clean = r − A ŵ,  ŵ = argmin ‖r − A w‖² + lam‖w‖²

    r: [d]   A: [d, k]（列为单位原子）
    """
    # (AᵀA + λI) w = Aᵀ r
    d, k = A.shape
    AtA = A.T @ A
    reg = lam * torch.eye(k, dtype=AtA.dtype)
    w = torch.linalg.solve(AtA + reg, A.T @ r)
    return r - A @ w


def collect_means(model, tok, device, max_len, limit, log=print):
    """返回 dict: set_name -> {layer_idx: vector}

    limit>0 时每集合取前 N 条（冒烟）；limit=0 时按 CAP 截断，
    避免 harmless_alpaca 的 25k 条把前向时间拉爆。
    """
    from datasets import load_dataset

    CAP = 400  # 与 harmful_behaviors 的 416 条同量级

    def take(texts):
        n = limit if limit and limit > 0 else CAP
        return texts[:n]

    log("[data] harmful_behaviors / harmless_alpaca")
    harmful = take(list(load_dataset("mlabonne/harmful_behaviors", split="train")["text"]))
    harmless = take(list(load_dataset("mlabonne/harmless_alpaca", split="train")["text"]))

    sets: dict[str, list[str]] = {"harmful": harmful, "harmless": harmless}
    for name, (pos, neg) in ATOMS.items():
        sets[f"atom:{name}:pos"] = pos
        sets[f"atom:{name}:neg"] = neg

    layers = model.model.language_model.layers
    out: dict[str, dict[int, torch.Tensor]] = {}
    for name, texts in sets.items():
        log(f"[forward] {name}  ({len(texts)} prompts)")
        toks = load_tokens(tok, texts, max_len)
        out[name] = mean_residual(layers, toks, max_len, device)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--layers", default="6-24", help="消融层范围，如 6-24")
    # Qwen3.5 是混合注意力：linear_attention 层叫 linear_attn.out_proj，
    # full_attention 层叫 self_attn.o_proj —— 两者都要覆盖（32 down + 24 out + 8 o = 64）
    ap.add_argument("--targets", default="down_proj,o_proj,out_proj")
    ap.add_argument("--gamma", type=float, default=1.0, help="rank-one 投影强度")
    ap.add_argument("--lambda-ridge", type=float, default=1e-2)
    ap.add_argument("--passes", type=int, default=1, help="硬负样本迭代轮数")
    ap.add_argument("--max-len", type=int, default=256)
    ap.add_argument("--limit", type=int, default=0, help=">0 时每集合只取前 N 条（冒烟用）")
    ap.add_argument("--shard-bytes", type=float, default=4 * 2**30)
    ap.add_argument("--dry-run", action="store_true", help="只算方向并打印诊断，不改权重")
    a = ap.parse_args()

    global _FORWARD
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "hf"))

    from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

    device = "cuda"
    log = print
    log(f"[model] {a.model}")
    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    model = AutoModelForImageTextToText.from_pretrained(
        a.model, quantization_config=bnb, dtype=torch.bfloat16,
        device_map={"": 0}, trust_remote_code=True, attn_implementation="sdpa")
    model.eval()

    def fwd(ids):
        return model(input_ids=ids, use_cache=False)

    _FORWARD = fwd

    n_layers = model.config.text_config.num_hidden_layers
    layers = parse_layers(a.layers, n_layers)
    log(f"[layers] {layers[0]}..{layers[-1]} ({len(layers)} 层) / 共 {n_layers}")

    means = collect_means(model, tok, device, a.max_len, a.limit, log)

    # ── 每层算 r_dirty / 原子矩阵 / r_clean ─────────────────────────
    atom_names = list(ATOMS)
    ridge = a.lambda_ridge
    summary = []
    directions: dict[int, torch.Tensor] = {}
    for li in layers:
        r_dirty = means["harmful"][li] - means["harmless"][li]
        cols = []
        for an in atom_names:
            v = means[f"atom:{an}:pos"][li] - means[f"atom:{an}:neg"][li]
            cols.append(v / (v.norm() + 1e-8))
        A = torch.stack(cols, dim=1)          # [d, k]
        r_clean = ridge_residualize(r_dirty, A, ridge)
        directions[li] = r_clean
        cos_before = [float(torch.dot(r_dirty / (r_dirty.norm() + 1e-8), A[:, i])) for i in range(len(atom_names))]
        cos_after = [float(torch.dot(r_clean / (r_clean.norm() + 1e-8), A[:, i])) for i in range(len(atom_names))]
        summary.append({
            "layer": li,
            "r_dirty_norm": float(r_dirty.norm()),
            "r_clean_norm": float(r_clean.norm()),
            "energy_removed": 1.0 - float(r_clean.norm() / (r_dirty.norm() + 1e-8)),
            "cos_dirty": dict(zip(atom_names, [round(c, 4) for c in cos_before])),
            "cos_clean": dict(zip(atom_names, [round(c, 4) for c in cos_after])),
        })
        log(f"[layer {li:2d}] |r_dirty|={r_dirty.norm():.3f} |r_clean|={r_clean.norm():.3f} "
            f"removed={summary[-1]['energy_removed']:.1%}")

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "sra-directions.json"), "w", encoding="utf-8") as f:
        json.dump({"layers": layers, "gamma": a.gamma, "lambda": ridge,
                   "targets": a.targets.split(","), "summary": summary}, f, indent=2)
    # 向量本身单独存，便于换 gamma 复算而不必重跑前向
    torch.save({li: directions[li] for li in layers},
               os.path.join(a.out, "sra-vectors.pt"))
    log(f"[save] {a.out}/sra-directions.json + sra-vectors.pt")

    if a.dry_run:
        log("[dry-run] 只输出方向诊断，未改权重")
        return 0

    # ── 释放 GPU 模型，流式改写 bf16 权重 ─────────────────────────
    del model
    gc.collect()
    torch.cuda.empty_cache()

    src = os.path.join(a.model, "model.safetensors")
    if not os.path.isfile(src):
        sys.exit(f"[FATAL] 需要单文件 safetensors: {src}")

    from safetensors import safe_open
    from safetensors.torch import save_file

    targets = a.targets.split(",")
    v_by_layer = {li: (directions[li] / (directions[li].norm() + 1e-8)) for li in layers}

    def layer_of(name: str):
        if ".language_model.layers." not in name:
            return None
        try:
            return int(name.split(".language_model.layers.")[1].split(".")[0])
        except (IndexError, ValueError):
            return None

    def should_edit(name: str):
        li = layer_of(name)
        if li is None or li not in v_by_layer:
            return None
        if not any(name.endswith(t + ".weight") for t in targets):
            return None
        return li

    log("[apply] 流式改写权重（读原文件 → 改目标张量 → 分片写出）")
    shard_limit = int(a.shard_bytes)
    shard_idx, shard_bytes, buf = 0, 0, {}
    weight_map: dict[str, str] = {}
    edited = 0

    def flush():
        nonlocal shard_idx, shard_bytes, buf
        if not buf:
            return
        fname = f"model-{shard_idx:05d}.safetensors"
        save_file(buf, os.path.join(a.out, fname))
        for k in buf:
            weight_map[k] = fname
        log(f"  -> {fname}  ({len(buf)} tensors, {shard_bytes/2**30:.2f} GiB)")
        shard_idx += 1
        shard_bytes = 0
        buf = {}

    with safe_open(src, framework="pt") as f:
        keys = list(f.keys())
        total = len(keys)
        for i, k in enumerate(keys, 1):
            w = f.get_tensor(k)
            li = should_edit(k)
            if li is not None and w.shape[-2] == v_by_layer[li].numel():
                v = v_by_layer[li].float()        # 统一 float32 计算，别转 bf16
                W = w.float()
                proj = v @ W                      # [in]
                W = W - a.gamma * torch.outer(v, proj)
                w = W.to(torch.bfloat16).contiguous()
                edited += 1
            buf[k] = w
            shard_bytes += w.numel() * w.element_size()
            if shard_bytes >= shard_limit:
                flush()
        flush()

    with open(os.path.join(a.out, "model.safetensors.index.json"), "w", encoding="utf-8") as f:
        json.dump({"metadata": {"total_size": sum(
            os.path.getsize(os.path.join(a.out, n)) for n in set(weight_map.values()))},
            "weight_map": weight_map}, f, indent=2)

    # metadata 复制
    for name in ("config.json", "generation_config.json", "tokenizer.json",
                 "tokenizer_config.json", "processor_config.json",
                 "preprocessor_config.json", "chat_template.jinja"):
        s = os.path.join(a.model, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(a.out, name))

    log(f"[DONE] {a.out}  改写张量 {edited} 个 / {len(keys)}")
    log("[next] 用 llama.cpp 或 4bit 重新加载验证：拒率应降到 <10%，KL 应 <0.1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
