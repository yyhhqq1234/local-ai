#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""precompute_activations.py -- cache the input hidden states of layer `--cut`.

Why: a 12 GiB card cannot hold a 27B model, but it CAN hold layers `cut..63`
plus the head.  So the first `cut` layers are executed once here (on a >=24 GiB
card) and their output at the cut boundary is cached to disk.  Local training
then starts from that cached tensor instead of from token embeddings.

Per sample, `<out>/<idx>.pt` holds
    hidden  float16/bfloat16 [1, T, H]   input to layer `cut`      (cpu)
    labels  int64            [1, T]      -100 = masked             (cpu)
    attn    int64            [1, T]      1 = real token            (cpu)
    n       int                         T
    src     int                         source line index in --data
    mask    str                         "none" | "assistant"

Loss-mask semantics (deliberate):
    --mask none       labels = input_ids  -> the whole sequence contributes,
                      which is exactly what `train_kitty.py` does today:
                      trl 1.16.0 `SFTConfig.assistant_only_loss` defaults to
                      False and train_kitty never overrides it.  Default here,
                      so local incremental training matches the cloud run.
    --mask assistant  only assistant spans contribute; every other position is
                      -100.  Use when you want textbook SFT masking, accepting
                      that it differs from the cloud full run.

Usage
    python precompute_activations.py --model merged/Qwen3.8-27B-kittyrev \
        --cut 48 --data kitty-rev/data/large-mix/train.jsonl --ctx 512 \
        --out /root/autodl-tmp/kitty-rev/act-cache \
        --mask none --limit 0

    # inspect sizes without loading the model
    python precompute_activations.py ... --dry-run --limit 20

Peak VRAM: 4bit 27B weights (~12.6 GiB, text tower only) + one forward pass
buffer at ctx 512 (~1.5 GiB) -> well under 16 GiB.  Runs with inference_mode,
no autograd graph.
"""
import argparse
import json
import os
import sys
import time

import torch


def human(n):
    if n >= 2 ** 30:
        return f"{n / 2 ** 30:.2f} GiB"
    return f"{n / 2 ** 20:.1f} MiB"


def parse():
    ap = argparse.ArgumentParser(description="cache layer-K input activations for partial local LoRA")
    ap.add_argument("--model", required=True, help="merged HF 目录（含 config.json + safetensors）")
    ap.add_argument("--cut", type=int, default=48, help="在第 N 层之前 dump（默认 48）")
    ap.add_argument("--data", required=True, help="jsonl，每行含 messages")
    ap.add_argument("--ctx", type=int, default=512, help="最大 token 数（默认 512）")
    ap.add_argument("--out", required=True, help="act-cache 输出目录")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--mask", choices=["none", "assistant"], default="none",
                    help="loss mask 口径；none 与 train_kitty.py 一致（默认）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="只统计与试渲染，不加载模型、不落盘")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有 .pt（默认跳过 = 断点续跑）")
    ap.add_argument("--start", type=int, default=0, help="从第 N 条开始（分段跑）")
    ap.add_argument("--no-text-only", action="store_true", help="不强制 language_model_only")
    return ap.parse_args()


def load_rows(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((ln, json.loads(line)))
            except Exception as e:
                print(f"[warn] line {ln} JSON 解析失败：{e}")
    return rows


def assistant_mask(tok, messages, n_ids, full_ids):
    """Return a bool list of length n_ids: True where the token belongs to an assistant span.

    Computed by rendering cumulative prefixes; each prefix is checked to be an
    exact token prefix of the full sequence, otherwise the span is skipped and
    reported (we never guess a mask).
    """
    keep = [False] * n_ids
    ok_spans, bad_spans = 0, 0
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        try:
            pre = tok.apply_chat_template(messages[:i], tokenize=True, add_generation_prompt=True)
            upto = tok.apply_chat_template(messages[:i + 1], tokenize=True, add_generation_prompt=False)
        except Exception:
            bad_spans += 1
            continue
        a, b = len(pre), len(upto)
        if a >= b or b > n_ids:
            bad_spans += 1
            continue
        if list(full_ids[:a]) != list(pre):
            bad_spans += 1
            continue
        for j in range(a, b):
            keep[j] = True
        ok_spans += 1
    return keep, ok_spans, bad_spans


def main():
    a = parse()
    torch.manual_seed(a.seed)
    rows = load_rows(a.data)
    print(f"[data] rows={len(rows)} from {a.data}")
    if a.start >= len(rows):
        print("[done] --start 超出样本数")
        return 0
    work = rows[a.start:]
    if a.limit:
        work = work[:a.limit]
    print(f"[data] work={len(work)} (start={a.start} limit={a.limit}) mask={a.mask} ctx={a.ctx}")

    from transformers import AutoConfig, AutoTokenizer

    cfg = AutoConfig.from_pretrained(a.model, trust_remote_code=True)
    tcfg = getattr(cfg, "text_config", cfg)
    n_layers = int(getattr(tcfg, "num_hidden_layers", 0))
    hidden = int(getattr(tcfg, "hidden_size", 0))
    print(f"[cfg] model_type={getattr(cfg, 'model_type', '?')} arch={getattr(cfg, 'architectures', None)} "
          f"layers={n_layers} hidden={hidden}")
    if not (0 < a.cut <= n_layers):
        print(f"[FATAL] --cut {a.cut} 超出范围 1..{n_layers}")
        return 2

    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)

    if a.dry_run:
        tot_tok = 0
        tot_bytes = 0
        for k, (ln, ex) in enumerate(work[:20]):
            msgs = ex.get("messages") or []
            text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            ids = tok(text, add_special_tokens=False)["input_ids"][:a.ctx]
            tot_tok += len(ids)
            tot_bytes += len(ids) * hidden * 2 + len(ids) * 8
            if k < 3:
                print(f"[dry] src={ln} msgs={len(msgs)} chars={len(text)} tokens={len(ids)}")
        n = max(1, min(20, len(work)))
        per = tot_bytes / n
        print(f"[dry-run] 样例均 {tot_tok / n:.0f} tok → 每样本 ≈ {human(per)}")
        print(f"[dry-run] 全量 {len(work)} 条 ≈ {human(per * len(work))}"
              f"（hidden {human(per * 0.99)} + labels/attn）")
        print(f"[dry-run] 每样本张量：hidden[1,T,{hidden}] labels[1,T] attn[1,T]")
        print("[dry-run] 未加载模型、未落盘")
        return 0

    from transformers import AutoModelForCausalLM, BitsAndBytesConfig

    if not a.no_text_only:
        cfg.language_model_only = True
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        a.model, config=cfg, quantization_config=bnb, device_map={"": 0},
        dtype=torch.bfloat16, trust_remote_code=True)
    model.eval()
    print(f"[load] done {time.time() - t0:.1f}s  vram={torch.cuda.memory_allocated() / 2 ** 30:.2f} GiB")

    backbone = model.model
    if hasattr(backbone, "language_model"):
        backbone = backbone.language_model
    layers = backbone.layers
    if len(layers) != n_layers:
        print(f"[warn] backbone.layers={len(layers)} 与 config={n_layers} 不一致，按实际 {len(layers)} 用")
        n_layers = len(layers)
    target = layers[a.cut]

    cache = {}

    def pre_hook(mod, args, kwargs):
        h = kwargs.get("hidden_states")
        if h is None and args:
            h = args[0]
        cache["h"] = h.detach()

    hd = target.register_forward_pre_hook(pre_hook, with_kwargs=True)

    os.makedirs(a.out, exist_ok=True)
    manifest_path = os.path.join(a.out, "manifest.json")
    manifest = {"model": os.path.abspath(a.model), "cut": a.cut, "ctx": a.ctx,
                "mask": a.mask, "hidden_size": hidden, "n_layers": n_layers,
                "seed": a.seed, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "samples": [], "skipped": [], "truncated": 0, "mask_bad_spans": 0}

    kept = total_tok = 0
    t1 = time.time()
    try:
        for k, (ln, ex) in enumerate(work):
            dst = os.path.join(a.out, f"{ln}.pt")
            if os.path.exists(dst) and not a.overwrite:
                kept += 1
                continue
            msgs = ex.get("messages") or []
            try:
                text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            except Exception as e:
                manifest["skipped"].append({"src": ln, "why": f"template: {e}"})
                print(f"[skip] src={ln} template 失败: {e}")
                continue
            ids = tok(text, add_special_tokens=False)["input_ids"]
            if len(ids) > a.ctx:
                ids = ids[:a.ctx]
                manifest["truncated"] += 1
            if len(ids) < 8:
                manifest["skipped"].append({"src": ln, "why": f"too short ({len(ids)} tok)"})
                continue

            input_ids = torch.tensor([ids], dtype=torch.long, device="cuda:0")
            attn = torch.ones_like(input_ids)
            labels = input_ids.clone()
            if a.mask == "assistant":
                keep, ok, bad = assistant_mask(tok, msgs, len(ids), ids)
                manifest["mask_bad_spans"] += bad
                labels = torch.tensor(
                    [[t if keep[j] else -100 for j, t in enumerate(ids)]],
                    dtype=torch.long, device="cuda:0")
                if labels[0].ne(-100).sum().item() == 0:
                    ok, bad = 0, bad + 1
                    manifest["mask_bad_spans"] += 1
                    # fall through: keep the sample with a single last-token label
                    labels = torch.full_like(input_ids, -100)
                    labels[0, -1] = input_ids[0, -1]

            cache.clear()
            with torch.inference_mode():
                backbone(input_ids=input_ids, attention_mask=attn, use_cache=False)
            h = cache.get("h")
            if h is None:
                manifest["skipped"].append({"src": ln, "why": "hook 未捕获 hidden"})
                print(f"[skip] src={ln} hook 未捕获")
                continue
            T = int(h.shape[1])
            payload = {"hidden": h.to(torch.bfloat16).cpu().contiguous(),
                       "labels": labels[0].unsqueeze(0).cpu().contiguous(),
                       "attn": attn[0].unsqueeze(0).cpu().contiguous(),
                       "n": T, "src": ln, "mask": a.mask}
            torch.save(payload, dst)
            total_tok += T
            if k % 20 == 0 or k + 1 == len(work):
                el = time.time() - t1
                print(f"[{k + 1}/{len(work)}] src={ln} T={T} "
                      f"vram={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB "
                      f"{el / max(1, k + 1):.2f}s/sample")
            del input_ids, attn, labels, payload, h
    finally:
        hd.remove()

    files = sorted(f for f in os.listdir(a.out) if f.endswith(".pt"))
    tot_bytes = sum(os.path.getsize(os.path.join(a.out, f)) for f in files)
    manifest.update({"samples": files, "count": len(files), "bytes": tot_bytes,
                     "tokens": total_tok, "skipped_count": len(manifest["skipped"])})
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[done] {len(files)} 个样本（本次新写 {len(files) - kept}，跳过已存在 {kept}）"
          f"  {human(tot_bytes)}  tokens={total_tok}  "
          f"vram_peak={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB  "
          f"用时 {time.time() - t1:.0f}s")
    if manifest["skipped"]:
        print(f"[done] 跳过 {len(manifest['skipped'])} 条（见 manifest.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
