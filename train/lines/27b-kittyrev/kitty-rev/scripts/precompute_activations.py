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

Silent-failure guards (all added after a measured silent-wrong incident):
  * assistant spans are located by CHARACTER OFFSET + verified by decoding the
    span back; `apply_chat_template(tokenize=True)` returns a BatchEncoding in
    transformers 5.x, and the old prefix comparison read `len()` = 2 fields, so
    every span was "bad" and labels fell back to a single last token.
  * a sample with 0 locatable assistant tokens is SKIPPED and listed in
    manifest["mask_bad"], never silently reduced to one label.
  * resuming into an out dir whose manifest has a different cut/ctx/mask/model
    or a different --data content hash is a FATAL (use --overwrite to rebuild).
  * .pt is written to `<name>.pt.tmp` then renamed, so a crash cannot leave a
    truncated file that the resume path treats as done.
  * manifest["samples"] is ordered by the trainer's own key (len, name), so
    samples[i] is really the i-th file MultiCache loads.

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
import glob
import hashlib
import json
import os
import re
import sys
import time

import torch


def human(n):
    if n >= 2 ** 30:
        return f"{n / 2 ** 30:.2f} GiB"
    return f"{n / 2 ** 20:.1f} MiB"


# 写进 manifest.engine.version；跑 act-cache 的机器用它判断缓存是不是旧版写的。
# v1: assistant span 用累计前缀 + BatchEncoding 的 len() → 全判 bad（坏缓存）
# v2: 字符 offset 映射 + 逐段解码回验
SCRIPT_VERSION = 2


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha16_file(path, cap=None):
    """sha256 前 16 位；cap 给定时只读前 N 字节（大 shard 做指纹用，秒级）。"""
    h = hashlib.sha256()
    left = cap
    with open(path, "rb") as f:
        while True:
            n = 1 << 20 if left is None else min(1 << 20, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h.hexdigest()[:16]


def model_fingerprint(model_dir, head_cap=1 << 20):
    """act-cache 与 base **逐比特绑定**：给出该模型目录的内容指纹。

    旧代码只比 `manifest["model"]` 的**路径字符串**（os.path.abspath）。
    路径不变、内容换了（v4 把 Huihui 下到 v3 的 base/Huihui 路径；
    或者 merged 目录被下一次 merge 覆盖）→ resume 判定「口径一致」，
    旧 .pt 被当新缓存复用：不报错，hidden 是上一版模型的第 48 层。
    所以指纹取 config.json + index.json 的 sha16 + 首个 shard 的
    「文件名 / 字节数 / 前 1 MiB sha16」—— 换基座必变，同一目录重跑不变。
    """
    fp = {"dir": os.path.abspath(model_dir)}
    for key, name in (("config", "config.json"), ("index", "model.safetensors.index.json")):
        q = os.path.join(model_dir, name)
        fp[f"{key}16"] = sha16_file(q) if os.path.isfile(q) else None
        fp[f"{key}_present"] = os.path.isfile(q)
    shards = sorted(f for f in os.listdir(model_dir)
                    if f.endswith(".safetensors") and "index" not in f)         if os.path.isdir(model_dir) else []
    fp["n_shards"] = len(shards)
    if shards:
        first = os.path.join(model_dir, shards[0])
        fp["first_shard"] = shards[0]
        fp["first_shard_bytes"] = os.path.getsize(first)
        fp["first_shard16"] = sha16_file(first, cap=head_cap)
        fp["first_shard_head_bytes"] = min(head_cap, os.path.getsize(first))
    return fp


def fp_diffs(prev_fp, cur_fp):
    """比较两份指纹，返回人类可读的差异列表（空 = 同一份模型内容）。"""
    if not prev_fp:
        return ["旧 manifest 没有 model_fp（无法证明缓存来自同一份权重）"]
    out = []
    for k in ("config16", "index16", "first_shard", "first_shard_bytes",
              "first_shard16", "n_shards"):
        a, b = prev_fp.get(k), cur_fp.get(k)
        if a != b:
            out.append(f"model_fp.{k}: 旧={a!r} 新={b!r}")
    return out


def order_key(path):
    """The order the trainer actually walks: numeric for `0.pt .. N.pt`.

    train_partial_lora.MultiCache sorts by `(len(basename), basename)`, which is
    numeric as long as names are plain integers.  The manifest must list samples
    in that SAME order: the old code wrote `sorted(os.listdir())`, i.e.
    `0,1,10,11,2,...`, so `samples[i]` was not the i-th file the loader loaded.
    Nothing zips them today (the guard is set-based), but the trap costs nothing
    to remove.
    """
    b = os.path.basename(path)
    return (len(b), b)


def parse():
    ap = argparse.ArgumentParser(description="cache layer-K input activations for partial local LoRA")
    ap.add_argument("--model", required=True, help="merged HF 目录（含 config.json + safetensors）")
    ap.add_argument("--cut", type=int, default=48, help="在第 N 层之前 dump（默认 48）")
    ap.add_argument("--data", required=True, help="jsonl，每行含 messages")
    ap.add_argument("--ctx", type=int, default=512, help="最大 token 数（默认 512）")
    ap.add_argument("--out", required=True, help="act-cache 输出目录")
    ap.add_argument("--split-by-subsets", default="",
                    help="按 make_subsets.py 的输出目录分目录落盘（re-train/re-val/... + rest）。"
                         "只做一次前向，用内容哈希归属；不传则保持旧的单目录行为")
    ap.add_argument("--allow-subset-mismatch", action="store_true",
                    help="--data 里有行没落进任何子集（例如 subsets 是旧数据切的、"
                         "forge 行会全进 rest）时只警告不退出")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--mask", choices=["none", "assistant"], default="none",
                    help="loss mask 口径；none 与 train_kitty.py 一致（默认）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="只统计与试渲染，不加载模型、不落盘")
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有 .pt（默认跳过 = 断点续跑）")
    ap.add_argument("--start", type=int, default=0, help="从第 N 条开始（分段跑）")
    ap.add_argument("--no-text-only", action="store_true", help="不强制 language_model_only")
    ap.add_argument("--reuse-unverified-model", action="store_true",
                    help="允许复用「旧 manifest 没有 model_fp」的缓存（会打印无法证明的部分）。"
                         "默认 FATAL —— v3 的 act-cache 在 v4 下被误用是静默错")
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


def _as_ids(x):
    """Token ids out of whatever `apply_chat_template(tokenize=True)` returned.

    transformers 5.x returns a `BatchEncoding`, and `len(BatchEncoding)` is the
    number of FIELDS (2), not the number of tokens -- so the old `len(pre)` /
    `list(pre)` prefix check compared token ids against dict keys.  Every
    assistant span came out "bad", `--mask assistant` wrote labels that were all
    -100, and the fallback below trained on a single last token per sample
    without any error.  Normalise first, always.
    """
    if hasattr(x, "input_ids"):
        return list(x.input_ids)
    if isinstance(x, (list, tuple)) and x and hasattr(x[0], "input_ids"):
        return list(x[0].input_ids)
    if isinstance(x, dict) and "input_ids" in x:
        return list(x["input_ids"])
    return list(x)


def assistant_mask(tok, messages, n_ids, full_ids, full_text=None):
    """Return (bool[] length n_ids, ok_spans, bad_spans): True on assistant token spans.

    Two independent traps, both silent:
      1) `len()` on a BatchEncoding is 2, not T (see _as_ids).
      2) The cumulative-prefix trick is invalid for this chat template: the
         prefix rendered with add_generation_prompt=True ends with `<think>`,
         while the full render continues `<think>\\n\\n</think>\\n\\n...`, so the
         prefix is a CHARACTER prefix but not a TOKEN prefix (BPE merges across
         the boundary differ).  Measured on re-subset row 0: prefix tokens = 62,
         true content span = 64..171.

    So the mask is located by character offset (`return_offsets_mapping`) and
    every span is VERIFIED by decoding it back and comparing to the message
    content; a span that cannot be verified is counted as bad, never guessed.
    """
    keep = [False] * n_ids
    ok_spans, bad_spans = 0, 0
    offs = None
    if full_text is not None:
        try:
            enc = tok(full_text, add_special_tokens=False, return_offsets_mapping=True)
            offs = list(enc["offset_mapping"])
        except Exception:
            offs = None

    if offs is not None:
        cursor = 0
        for m in messages:
            if m.get("role") != "assistant":
                continue
            content = (m.get("content") or "").strip()
            if not content:
                bad_spans += 1
                continue
            c0 = full_text.find(content, cursor)
            if c0 < 0:
                bad_spans += 1
                continue
            c1 = c0 + len(content)
            got = None
            # exact-start first, then the token that straddles the boundary
            for pick in (lambda o: o[0] >= c0, lambda o: o[1] > c0):
                s = next((k for k, o in enumerate(offs) if pick(o)), None)
                e = next((k for k, o in enumerate(offs) if o[1] >= c1), None)
                if s is None or e is None or s > e or e >= n_ids:
                    continue
                if tok.decode(full_ids[s:e + 1], skip_special_tokens=True).strip() == content:
                    got = (s, e + 1)
                    break
            if got is None:
                bad_spans += 1
                continue
            for j in range(*got):
                keep[j] = True
            cursor = c1
            ok_spans += 1
        return keep, ok_spans, bad_spans

    # slow tokenizer without offset mapping: old prefix method, ids taken correctly
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        try:
            pre = _as_ids(tok.apply_chat_template(messages[:i], tokenize=True,
                                                 add_generation_prompt=True))
            upto = _as_ids(tok.apply_chat_template(messages[:i + 1], tokenize=True,
                                                  add_generation_prompt=False))
        except Exception:
            bad_spans += 1
            continue
        a, b = len(pre), len(upto)
        if a >= b or b > n_ids or list(full_ids[:a]) != list(pre):
            bad_spans += 1
            continue
        for j in range(a, b):
            keep[j] = True
        ok_spans += 1
    return keep, ok_spans, bad_spans


def content_hash(row):
    """sha256 over normalised messages -- MUST stay byte-identical to the
    algorithm in make_subsets.py, otherwise the split map never matches."""
    msgs = row.get("messages") or []
    norm = [{"role": m.get("role", ""), "content": (m.get("content") or "").strip()}
            for m in msgs]
    blob = json.dumps(norm, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_subset_map(dirpath):
    """-> ({content_hash: 're-train' | 're-val' | ...}, {name: n_rows}).

    Reads `<dir>/*-subset.train.jsonl` and `*-subset.val.jsonl` only; the
    all-rows file (`re-subset.jsonl`) is deliberately ignored so a row is not
    counted twice.  A hash appearing in two different split files means the
    split leaked and is a hard error, never a silent pick.
    """
    m, info, dup = {}, {}, []
    for p in sorted(glob.glob(os.path.join(dirpath, "*.jsonl"))):
        base = os.path.basename(p)
        mm = re.match(r"^(.+)-subset\.(train|val)\.jsonl$", base)
        if not mm:
            continue
        name = f"{mm.group(1)}-{mm.group(2)}"
        hs = set()
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                hs.add(content_hash(json.loads(line)))
        clash = hs & set(m)
        if clash:
            dup.append({"file": base, "overlap": len(clash),
                        "other": sorted({m[h] for h in clash})})
            continue
        for h in hs:
            m[h] = name
        info[name] = len(hs)
    if dup:
        raise SystemExit(f"[FATAL] 子集切分泄漏，以下文件与已有集合重叠：{dup}")
    return m, info


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

    # ---- resume guard: refuse to mix caches built under different settings ----
    # The skip-if-exists path reuses `<line>.pt` blindly.  A second run with a
    # different --mask / --ctx / --cut, or a --data file that was rebuilt with
    # rows in another order, would keep the OLD tensors and add new ones: no
    # error, one cache with two incompatible mask conventions and stale rows.
    data_sha = file_sha256(a.data)
    data_bytes = os.path.getsize(a.data)
    # 与 base 逐比特绑定：路径字符串不作数，比起指纹（config/index/首 shard）
    model_fp = model_fingerprint(a.model)
    os.makedirs(a.out, exist_ok=True)
    manifest_path = os.path.join(a.out, "manifest.json")
    if not a.dry_run and not a.overwrite and os.path.exists(manifest_path):
        try:
            prev = json.load(open(manifest_path, encoding="utf-8"))
        except Exception as e:
            raise SystemExit(f"[FATAL] {manifest_path} 读不了（{e}）；加 --overwrite 重算")
        diffs = []
        # 版本闸门：v1 的 --mask assistant 是坏的（assistant span 全判 bad →
        # labels 全 -100 → 兜底成单 token）。v1 + --mask none 不受影响（labels =
        # input_ids，与 v2 逐字节相同），所以只白名单这一种组合，其余一律要求重算。
        old_ver = (prev.get("engine") or {}).get("version")
        reuse_ok = (old_ver != SCRIPT_VERSION and a.mask == "none"
                    and prev.get("mask") == "none")
        if old_ver != SCRIPT_VERSION and not reuse_ok:
            diffs.append(f"缓存由旧版脚本写入（engine={prev.get('engine')!r}，当前 v{SCRIPT_VERSION}）："
                         f"旧版 --mask assistant 会写出全 -100 的 labels")
        elif reuse_ok:
            print(f"[resume] 旧版缓存 + --mask none：labels 与 v2 同构，按可续用放行"
                  f"（仅补写 manifest 的 engine 字段）")
        for k in ("cut", "ctx", "mask"):
            if k in prev and prev[k] != getattr(a, k, prev[k]):
                diffs.append(f"{k}: 旧={prev[k]!r} 新={getattr(a, k)!r}")
        if prev.get("model") and prev["model"] != os.path.abspath(a.model):
            diffs.append(f"model: 旧={prev['model']} 新={os.path.abspath(a.model)}")
        mp = prev.get("model_fp")
        if mp:
            mdiff = fp_diffs(mp, model_fp)
            if a.reuse_unverified_model:
                print(f"[warn] --reuse-unverified-model：忽略 {len(mdiff)} 项 model_fp 差异")
            elif mdiff:
                diffs.extend(f"base 权重换了：{d}" for d in mdiff)
        elif a.reuse_unverified_model:
            print("[warn] 旧 manifest 无 model_fp，--reuse-unverified-model 放行："
                  "本次无法证明 .pt 来自当前 --model（v3/v4 混用就是这么产生的）")
        else:
            diffs.append("旧 manifest 没有 model_fp（act-cache 与 base 逐比特绑定，"
                         "无法证明这批 .pt 来自当前 --model）")
        pd = prev.get("data") or {}
        if pd.get("sha256") and pd["sha256"] != data_sha:
            diffs.append(f"--data 内容已变（旧 sha {pd['sha256'][:12]} → 新 {data_sha[:12]}）；"
                         f"行号即文件名，行序一变 <idx>.pt 就名不副实")
        if diffs:
            raise SystemExit("[FATAL] 输出目录已有另一套口径的缓存，继续会混用旧 .pt：\n  - "
                             + "\n  - ".join(diffs) + "\n确认要全部重算请加 --overwrite")
            print(f"[fp] base 指纹 config={model_fp.get('config16')} "
              f"idx={model_fp.get('index16')} 首shard={model_fp.get('first_shard')}"
              f"/{model_fp.get('first_shard_bytes')}B/{model_fp.get('first_shard16')}")
        print(f"[resume] 与 {manifest_path} 口径一致（cut/ctx/mask/base指纹/--data 全部相同）")

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

    # ---- optional per-subset bucketing (one forward pass, hash-routed) ------
    subset_map, subset_info, split_dist = {}, {}, {}
    if a.split_by_subsets:
        subset_map, subset_info = load_subset_map(a.split_by_subsets)
        if not subset_map:
            print(f"[split][FATAL] {a.split_by_subsets} 里没有 *-subset.{{train,val}}.jsonl")
            return 2
        for _ln, ex in work:
            nm = subset_map.get(content_hash(ex), "rest")
            split_dist[nm] = split_dist.get(nm, 0) + 1
        print(f"[split] 子集 {len(subset_info)} 个 / 唯一哈希 {len(subset_map)} 条  "
              f"（dir={a.split_by_subsets}）")
        for nm in sorted(split_dist):
            tag = "  ← 未命中任何子集" if nm == "rest" else ""
            print(f"[split]   {nm:16s} {split_dist[nm]:4d} 条{tag}")
        missed = sorted(set(subset_info) - set(split_dist))
        if missed:
            print(f"[split][warn] 这些子集在 --data 里 0 命中: {missed}")

        # ---- 新鲜度闸门（在加载 27B 之前就判）--------------------------------
        # subsets 是独立生成物：若它由旧的 train.jsonl 切出，而 --data 已经换成
        # large-mix-plus，forge 行不会有对应的 *-subset.*.jsonl → 全部落 rest，
        # 于是"新能力数据"被当成通用回放、权重 1、也没有验证集。旧代码只在 26 分钟
        # 跑完后打一行 ⚠。这里在加载模型前直接说清楚。
        forge_like = [ex for _ln, ex in work if (ex.get("meta") or {}).get("forge")]
        if forge_like:
            forge_in_subset = sum(1 for ex in forge_like if content_hash(ex) in subset_map)
            if forge_in_subset < len(forge_like):
                msg = (f"--data 里 {len(forge_like)} 条带 meta.forge 的行中，"
                       f"{len(forge_like) - forge_in_subset} 条没有落进任何子集 → 会进 rest"
                       f"（按回放权重 1 训练，且没有任何验证集）")
                if not a.allow_subset_mismatch:
                    print(f"[split][FATAL] {msg}")
                    print("[split][FATAL] 先重跑 make_subsets.py --data <同一个 --data> "
                          "再跑本脚本；确认知道后果可加 --allow-subset-mismatch")
                    return 2
                print(f"[split][warn] {msg}（--allow-subset-mismatch 已放行）")
            else:
                print(f"[split] forge 行 {len(forge_like)} 条全部命中子集 ✓")
        # 反向：某个子集的命中数远少于 jsonl 行数 → 两边不是同一份数据
        shorts = [(nm, subset_info[nm], split_dist.get(nm, 0)) for nm in subset_info
                  if split_dist.get(nm, 0) < subset_info[nm] * 0.5]
        if shorts:
            print(f"[split][warn] 命中数不到子集规模一半（subsets 与 --data 可能不是同一版本）：")
            for nm, exp, got in sorted(shorts):
                print(f"[split][warn]   {nm:16s} jsonl {exp:4d} 条 → 命中 {got:4d}")

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
    manifest = {"model": os.path.abspath(a.model), "model_fp": model_fp,
                "cut": a.cut, "ctx": a.ctx,
                "mask": a.mask, "hidden_size": hidden, "n_layers": n_layers,
                "seed": a.seed, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "engine": {"script": "precompute_activations.py",
                           "version": SCRIPT_VERSION,
                           "mask_impl": "char-offset-map+decode-verify"},
                "data": {"path": os.path.abspath(a.data), "sha256": data_sha,
                         "bytes": data_bytes, "rows": len(rows)},
                "mask_semantics": ("none: labels=input_ids（与 train_kitty 一致）"
                                   if a.mask == "none" else
                                   "assistant: 只掩 assistant 正文 token，不含 <|im_end|> 等 turn-end 标记"),
                "samples": [], "skipped": [], "truncated": 0, "mask_bad_spans": 0,
                "mask_bad": [], "skipped_by_subset": {}}

    kept = total_tok = 0
    written_by_subset = {}
    t1 = time.time()
    try:
        for k, (ln, ex) in enumerate(work):
            sub = subset_map.get(content_hash(ex), "rest") if subset_map else None
            dst_dir = os.path.join(a.out, sub) if sub else a.out
            dst = os.path.join(dst_dir, f"{ln}.pt")
            if os.path.exists(dst) and not a.overwrite:
                kept += 1
                written_by_subset[sub or "."] = written_by_subset.get(sub or ".", 0) + 1
                continue
            msgs = ex.get("messages") or []
            try:
                text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            except Exception as e:
                manifest["skipped"].append({"src": ln, "why": f"template: {e}"})
                manifest["skipped_by_subset"][sub or "."] = \
                    manifest["skipped_by_subset"].get(sub or ".", 0) + 1
                print(f"[skip] src={ln} template 失败: {e}")
                continue
            ids = tok(text, add_special_tokens=False)["input_ids"]
            if len(ids) > a.ctx:
                ids = ids[:a.ctx]
                manifest["truncated"] += 1
            if len(ids) < 8:
                manifest["skipped"].append({"src": ln, "why": f"too short ({len(ids)} tok)"})
                manifest["skipped_by_subset"][sub or "."] = \
                    manifest["skipped_by_subset"].get(sub or ".", 0) + 1
                continue

            input_ids = torch.tensor([ids], dtype=torch.long, device="cuda:0")
            attn = torch.ones_like(input_ids)
            labels = input_ids.clone()
            if a.mask == "assistant":
                keep, ok, bad = assistant_mask(tok, msgs, len(ids), ids, full_text=text)
                manifest["mask_bad_spans"] += bad
                labels = torch.tensor(
                    [[t if keep[j] else -100 for j, t in enumerate(ids)]],
                    dtype=torch.long, device="cuda:0")
                n_lab = int(labels[0].ne(-100).sum().item())
                if n_lab == 0:
                    # Old behaviour: fall through with a single last-token label.
                    # That silently turned "masking is broken" into "train on the
                    # final token only", i.e. a full cache of degenerate samples.
                    # A sample with nothing to predict is skipped and listed.
                    manifest["mask_bad"].append(
                        {"src": ln, "why": "assistant mask 0 命中", "ok_spans": ok,
                         "bad_spans": bad, "T": len(ids)})
                    manifest["skipped"].append(
                        {"src": ln, "why": f"assistant mask 无可用 span（ok={ok} bad={bad}）"})
                    manifest.setdefault("skipped_by_subset", {})[sub or "."] = \
                        manifest["skipped_by_subset"].get(sub or ".", 0) + 1
                    print(f"[skip] src={ln} --mask assistant 下 0 个可定位 assistant token"
                          f"（ok={ok} bad={bad}）")
                    continue
                if bad:
                    manifest["mask_bad"].append(
                        {"src": ln, "why": "部分 assistant 段未定位", "ok_spans": ok,
                         "bad_spans": bad, "labelled_tokens": n_lab, "T": len(ids)})

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
            os.makedirs(dst_dir, exist_ok=True)
            # atomic: a crash mid-save would otherwise leave a truncated .pt that
            # the resume path treats as "already done" (exists -> skip).
            tmp_dst = dst + ".tmp"
            torch.save(payload, tmp_dst)
            os.replace(tmp_dst, dst)
            written_by_subset[sub or "."] = written_by_subset.get(sub or ".", 0) + 1
            total_tok += T
            if k % 20 == 0 or k + 1 == len(work):
                el = time.time() - t1
                print(f"[{k + 1}/{len(work)}] src={ln} T={T} "
                      f"vram={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB "
                      f"{el / max(1, k + 1):.2f}s/sample")
            del input_ids, attn, labels, payload, h
    finally:
        hd.remove()

    if subset_map:
        # per-subset manifests so train_partial_lora can verify each source
        per_dir = {}
        for sub in sorted(set(list(subset_info) + ["rest"])):
            d = os.path.join(a.out, sub)
            if not os.path.isdir(d):
                continue
            fs = sorted((f for f in os.listdir(d) if f.endswith(".pt")), key=order_key)
            b = sum(os.path.getsize(os.path.join(d, f)) for f in fs)
            per_dir[sub] = {"dir": d, "count": len(fs), "bytes": b, "samples": fs,
                            "expected_from_subsets": subset_info.get(sub)}
            with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump({"subset": sub, "dir": d, "count": len(fs), "bytes": b,
                           "samples": fs, "cut": a.cut, "ctx": a.ctx, "mask": a.mask,
                           "hidden_size": hidden,
                           "engine_version": SCRIPT_VERSION,
                           "skipped": manifest["skipped_by_subset"].get(sub, 0),
                           "mask_semantics": manifest["mask_semantics"],
                           "data_sha256": data_sha,
                           "order": "sorted by (len(name), name) == MultiCache 的加载顺序",
                           "created": time.strftime("%Y-%m-%dT%H:%M:%S")},
                          f, ensure_ascii=False, indent=2)
        manifest["split_by_subsets"] = {
            "dir": os.path.abspath(a.split_by_subsets),
            "hash": "sha256(normalised messages, sort_keys=True)",
            "subset_rows": subset_info,
            "assigned": split_dist,
            "written": written_by_subset,
            "rest": split_dist.get("rest", 0),
            "per_dir": {k: {kk: v[kk] for kk in ("count", "bytes", "expected_from_subsets")}
                        for k, v in per_dir.items()},
        }
        files = []
        tot_bytes = 0
        for k, v in per_dir.items():
            files.extend([os.path.join(k, f) for f in v["samples"]])
            tot_bytes += v["bytes"]
        print(f"[split] 分目录落盘完成：")
        for k in sorted(per_dir):
            v = per_dir[k]
            exp = subset_info.get(k)
            mark = "" if exp is None else ("  ✓" if exp == v["count"] else f"  ⚠ 期望 {exp}")
            print(f"[split]   {k:16s} {v['count']:4d} 个 .pt{mark}")
    else:
        files = sorted((f for f in os.listdir(a.out) if f.endswith(".pt")), key=order_key)
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
