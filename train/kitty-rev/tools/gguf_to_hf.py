#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gguf (bf16) → HF safetensors 反解器 · V6.1 base 重建

背景（为什么需要它）：
  V6 期间 merged-v5 / merged-v6 两份 HF 权重都被删了，远程只剩 v6-bf16.gguf。
  bf16 的 gguf 张量本身是无损的（就是原始 bf16 权重，只是容器不同），
  所以「gguf → HF」可以视为无损重建，用于继续做 LoRA SFT。

两段模式：
  --inspect   只读，列出所有张量名 / shape / dtype，并按名字模式聚合
              （上机第一步先跑它，用真实名字确认映射表，不要凭记忆写映射）
  --convert   按映射表转换，剔除 MTP 块（blk.64.*），写出 safetensors 分片 + config.json

用法（远程）：
  # 1) 探查
  /root/miniconda3/bin/python gguf_to_hf.py --inspect \
      --gguf /root/autodl-tmp/kitty-rev/gguf/v6-bf16.gguf
  # 2) 转换
  /root/miniconda3/bin/python gguf_to_hf.py --convert \
      --gguf /root/autodl-tmp/kitty-rev/gguf/v6-bf16.gguf \
      --out  /root/autodl-tmp/kitty-rev/base-v61 \
      --cfg-json /root/autodl-tmp/kitty-rev/ninfer-v6/<name>.ninfer.conversion.json \
      --max-shard-bytes 5000000000

依赖：gguf（llama.cpp 的 gguf-py）、safetensors、torch（仅用于 dtype 映射，可省）
     缺 safetensors 时退化为逐张量 .bin（训练脚本也能读，但慢）
"""
import argparse, json, os, re, shutil, sys
from collections import defaultdict, Counter

# ── gguf 张量名 → HF 参数名 的映射规则 ───────────────────────────
# Qwen3.5 是混合架构（GDN/线性注意力 + 常规 attn），实际名字以 --inspect 输出为准。
# 这里给出一套按模式的正则映射，覆盖 llama.cpp 对 qwen 系列的常见命名。
# 任何一个 gguf 张量没被任何规则命中 → 转换中止并打印它（不允许静默丢张量）。
RULES = [
    # ★ MTP 块放最前：blk.64 除 nextn.* 外还有 attn/ffn/norm 共 11 个张量，全属 MTP 头，
    #   HF 的 851 keys 里没有 layers.64。顺序极重要，放末尾会被常规规则先匹配掉。
    (r"^blk\.(?:6[4-9]|[7-9]\d)\.",           None),
    # token embedding / output
    (r"^token_embd\.weight$",                 "model.embed_tokens.weight"),
    (r"^output\.weight$",                     "lm_head.weight"),
    (r"^output_norm\.weight$",                "model.norm.weight"),
    # 每层通用 norm
    (r"^blk\.(\d+)\.attn_norm\.weight$",      r"model.layers.\1.input_layernorm.weight"),
    (r"^blk\.(\d+)\.post_attention_norm\.weight$", r"model.layers.\1.post_attention_layernorm.weight"),
    (r"^blk\.(\d+)\.ffn_norm\.weight$",       r"model.layers.\1.post_attention_layernorm.weight"),
    # ── GDN / 线性注意力（48 层）—— 映射取自 transformers 建的模型 state_dict（终极真值）──
    #   language_model.layers.N.linear_attn.{A_log, conv1d, dt_bias, in_proj_a, in_proj_b,
    #                                       in_proj_qkv, in_proj_z, norm, out_proj}
    (r"^blk\.(\d+)\.attn_qkv\.weight$",       r"model.layers.\1.linear_attn.in_proj_qkv.weight"),
    (r"^blk\.(\d+)\.attn_gate\.weight$",      r"model.layers.\1.linear_attn.in_proj_z.weight"),
    (r"^blk\.(\d+)\.ssm_a$",                  r"model.layers.\1.linear_attn.A_log"),
    (r"^blk\.(\d+)\.ssm_a\.weight$",          r"model.layers.\1.linear_attn.A_log"),
    (r"^blk\.(\d+)\.ssm_dt\.bias$",           r"model.layers.\1.linear_attn.dt_bias"),
    (r"^blk\.(\d+)\.ssm_alpha\.weight$",      r"model.layers.\1.linear_attn.in_proj_a.weight"),
    (r"^blk\.(\d+)\.ssm_beta\.weight$",       r"model.layers.\1.linear_attn.in_proj_b.weight"),
    (r"^blk\.(\d+)\.ssm_conv1d\.weight$",     r"model.layers.\1.linear_attn.conv1d.weight"),
    (r"^blk\.(\d+)\.ssm_norm\.weight$",       r"model.layers.\1.linear_attn.norm.weight"),
    (r"^blk\.(\d+)\.ssm_out\.weight$",        r"model.layers.\1.linear_attn.out_proj.weight"),
    # ── 常规 attention（非 GDN 层）──
    (r"^blk\.(\d+)\.attn_q\.weight$",         r"model.layers.\1.self_attn.q_proj.weight"),
    (r"^blk\.(\d+)\.attn_k\.weight$",         r"model.layers.\1.self_attn.k_proj.weight"),
    (r"^blk\.(\d+)\.attn_v\.weight$",         r"model.layers.\1.self_attn.v_proj.weight"),
    (r"^blk\.(\d+)\.attn_output\.weight$",    r"model.layers.\1.self_attn.o_proj.weight"),
    (r"^blk\.(\d+)\.attn_q_norm\.weight$",    r"model.layers.\1.self_attn.q_norm.weight"),
    (r"^blk\.(\d+)\.attn_k_norm\.weight$",    r"model.layers.\1.self_attn.k_norm.weight"),
    # MLP
    (r"^blk\.(\d+)\.ffn_gate\.weight$",       r"model.layers.\1.mlp.gate_proj.weight"),
    (r"^blk\.(\d+)\.ffn_up\.weight$",         r"model.layers.\1.mlp.up_proj.weight"),
    (r"^blk\.(\d+)\.ffn_down\.weight$",       r"model.layers.\1.mlp.down_proj.weight"),
]
COMPILED = [(re.compile(p), tgt) for p, tgt in RULES]


def map_name(gname):
    for pat, tgt in COMPILED:
        m = pat.match(gname)
        if m:
            if tgt is None:
                return None                       # 明确丢弃
            return m.expand(tgt)
    return "?UNMAPPED?"


# ── dtype 归一：numpy 没有 bfloat16，破解见坑 A ───────────────────
def pick_dtype_backend():
    """选一个能无损保存 bf16 的后端：ml_dtypes > torch > 无"""
    try:
        import ml_dtypes  # noqa
        from safetensors.numpy import save_file  # noqa
        return "ml_dtypes"
    except ImportError:
        pass
    try:
        import torch  # noqa
        from safetensors.torch import save_file  # noqa
        return "torch"
    except ImportError:
        pass
    return None


def normalize_one(t, backend):
    """把 gguf 的一个 tensor 转成目标后端可存的 bf16/f32

    关键（踩过的坑）：
      gguf 的 t.data 是**原始字节**（uint8），不是已解释的数值数组。
      ttype=0  → F32（4 字节/元素）
      ttype=30 → BF16（2 字节/元素），numpy 没有 bfloat16，得用 uint16 视图 + ml_dtypes/torch
      t.shape 是**元素形状**（正确）；t.data.shape 是字节形状（会差一个字节倍数，别用）
    """
    import numpy as np
    tt = int(t.tensor_type)
    elem_shape = tuple(int(x) for x in t.shape)
    raw = t.data.view(np.uint8).reshape(-1)

    if tt == 0:                       # F32
        arr16 = raw.view(np.float32).reshape(elem_shape)
        if backend == "torch":
            import torch
            return torch.from_numpy(np.ascontiguousarray(arr16))
        return arr16
    elif tt == 30:                    # BF16
        arr16 = raw.view(np.uint16).reshape(elem_shape)
        if backend == "ml_dtypes":
            import ml_dtypes
            return arr16.view(ml_dtypes.bfloat16)
        if backend == "torch":
            import torch
            return torch.from_numpy(np.ascontiguousarray(arr16)).view(torch.bfloat16)
        return arr16
    else:
        raise ValueError(f"不支持的 tensor_type={tt}（{t.name}）；目前只处理 F32(0) 与 BF16(30)")


def get_gguf_reader(path):
    try:
        from gguf import GGUFReader
    except ImportError:
        print("[FATAL] 缺 gguf 库。llama.cpp 的 gguf-py 需要装：")
        print("        /root/miniconda3/bin/pip install gguf  或  "
              "cd llama.cpp/gguf-py && pip install -e .")
        sys.exit(2)
    return GGUFReader(path)


def inspect(path):
    r = get_gguf_reader(path)
    print(f"文件 {path}")
    print(f"张量数 {len(r.tensors)}")
    # 按"去掉数字"的模式聚合
    pat = Counter()
    for t in r.tensors:
        p = re.sub(r"\.\d+\.", ".N.", t.name)
        p = re.sub(r"^blk\.\d+\.", "blk.N.", p)
        pat[(p, tuple(t.shape), str(t.tensor_type))] += 1
    print(f"\n=== 名字模式聚合（{len(pat)} 种）===")
    for (p, shape, dt), n in sorted(pat.items(), key=lambda x: (-x[1], x[0][0])):
        print(f"  {n:>3} × {p:<58} shape={shape} dtype={dt}")
    # 映射覆盖检查
    print("\n=== 映射覆盖检查 ===")
    unmapped, dropped, ok = [], [], 0
    for t in r.tensors:
        m = map_name(t.name)
        if m is None:
            dropped.append(t.name)
        elif m == "?UNMAPPED?":
            unmapped.append(t.name)
        else:
            ok += 1
    print(f"  已映射 {ok} · 丢弃(blk.64 MTP) {len(dropped)} · **未映射 {len(unmapped)}**")
    if unmapped:
        print("  未映射清单（必须为 0，否则转换会中止）:")
        for n in unmapped[:30]:
            print("   ", n)
    print("\n=== 元数据关键项 ===")
    for k in ("general.architecture", "general.name", "qwen3_5.block_count",
              "qwen3_5.embedding_length", "qwen3_5.attention.head_count"):
        try:
            print(f"  {k} = {r.get_field(k)}")
        except Exception:
            pass
    return 0 if not unmapped else 1


def convert(path, out, cfg_json=None, max_shard_bytes=5_000_000_000, tokenizer_src=None):
    r = get_gguf_reader(path)
    backend = pick_dtype_backend()
    if backend is None:
        print("[FATAL] 既没有 ml_dtypes 也没有 torch → 无法无损保存 bf16。")
        print("        装一个：pip install ml_dtypes   或   pip install torch")
        print("        ⚠ 不要用 float32 兜底：52GB 会变 104GB，磁盘必爆")
        return 2
    print(f"[dtype] 后端 = {backend}")
    if backend == "ml_dtypes":
        from safetensors.numpy import save_file
    else:
        from safetensors.torch import save_file
    import numpy as np

    os.makedirs(out, exist_ok=True)
    tensors = {}
    unmapped, dropped, nbytes = [], 0, 0
    dtypes_seen = set()
    for t in r.tensors:
        m = map_name(t.name)
        if m is None:
            dropped += 1
            continue
        if m == "?UNMAPPED?":
            unmapped.append(t.name)
            continue
        arr = normalize_one(t, backend)
        dtypes_seen.add(str(getattr(arr, "dtype", type(arr))))
        # 计算字节数（torch 张量走 element_size）
        nb = arr.nbytes if hasattr(arr, "nbytes") else arr.nelement() * arr.element_size()
        tensors[m] = arr
        nbytes += nb
    if unmapped:
        print(f"[FATAL] 有 {len(unmapped)} 个张量未映射，拒绝写出（避免静默丢权重）:")
        for n in unmapped[:20]:
            print("   ", n)
        return 3

    print(f"转换: {len(tensors)} 张量 · {nbytes/1e9:.2f} GB · 丢弃 MTP {dropped} 个")
    print(f"实际 dtype 集合: {dtypes_seen}")
    if backend == "ml_dtypes" and any("float32" in d for d in dtypes_seen):
        print("[warn] 出现 float32 张量，若不是 norm 类小张量请核查（会让体积翻倍）")

    # 分片写出（backend 已在上面保证可用）
    shards, cur, cur_bytes = [], {}, 0
    for k, v in tensors.items():
        nb = v.nbytes if hasattr(v, "nbytes") else v.nelement() * v.element_size()
        if cur_bytes + nb > max_shard_bytes and cur:
            shards.append(cur); cur, cur_bytes = {}, 0
        cur[k] = v; cur_bytes += nb
    if cur:
        shards.append(cur)
    total = len(shards)
    index = {"metadata": {"total_size": int(nbytes)}, "weight_map": {}}
    for i, sh in enumerate(shards, 1):
        name = f"model-{i:05d}-of-{total:05d}.safetensors"
        save_file(dict(sh), os.path.join(out, name))
        for k in sh:
            index["weight_map"][k] = name
        nb_sh = sum((v.nbytes if hasattr(v, "nbytes") else v.nelement() * v.element_size())
                    for v in sh.values())
        print(f"  写出 {name}  {nb_sh/1e9:.2f} GB  {len(sh)} 张量")
    json.dump(index, open(os.path.join(out, "model.safetensors.index.json"), "w"),
              indent=2, ensure_ascii=False)

    # config.json
    cfg = None
    if cfg_json and os.path.exists(cfg_json):
        d = json.load(open(cfg_json, encoding="utf-8"))
        txt = (d.get("components") or {}).get("text") or {}
        cfg = txt.get("config")
    if not cfg:
        cfg = {"architectures": ["Qwen3_5ForConditionalGeneration"],
               "model_type": "qwen3_5",
               "_note": "config 来自 fallback，需人工核 hidden_size/layers/heads"}
        print("[warn] 没拿到可信 config，用了 fallback，训练前必须人工核对")
    else:
        print("config.json 来源：conversion.json 的 components.text.config")
    # 顶层要保持多模态形态（与 merged-v5 一致），text 子配置放 language_model
    if "language_model" not in cfg and cfg.get("architectures"):
        pass
    json.dump(cfg, open(os.path.join(out, "config.json"), "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    # ── 拷 tokenizer（坑 B：不拷则 AutoTokenizer.from_pretrained 直接崩）──
    TOK_FILES = ["tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
                 "special_tokens_map.json", "vocab.json", "merges.txt",
                 "generation_config.json", "added_tokens.json"]
    if tokenizer_src and os.path.isdir(tokenizer_src):
        copied = []
        for fn in TOK_FILES:
            src = os.path.join(tokenizer_src, fn)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(out, fn))
                copied.append(fn)
        print(f"\ntokenizer 从 {tokenizer_src} 拷入 {len(copied)} 个文件：{copied}")
        critical = [f for f in ("tokenizer.json", "tokenizer_config.json") if f not in copied]
        if critical:
            print(f"[FATAL] tokenizer 关键文件缺失 {critical} → 训练会在 AutoTokenizer 阶段崩")
            return 4
    else:
        print("\n[warn] 没指定 --tokenizer-src：base 目录不含 tokenizer，训练前必须手工补")
        print("       来源：/root/autodl-tmp/kitty-rev/out-v6/adapter/  或  .../cfg-vision/")

    print(f"\n完成 → {out}")
    print(f"  config.architectures = {cfg.get('architectures')}")
    print(f"  config.model_type    = {cfg.get('model_type')}")
    print(f"  分片数 = {len(shards)}")
    print("\n训练前必做 sanity check：")
    print("  python -c \"from transformers import AutoModelForCausalLM;"
          "m=AutoModelForCausalLM.from_pretrained('%s');print(type(m).__name__, sum(p.numel() for p in m.parameters()))\"" % out)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--convert", action="store_true")
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--out")
    ap.add_argument("--cfg-json")
    ap.add_argument("--max-shard-bytes", type=int, default=5_000_000_000)
    ap.add_argument("--tokenizer-src", default=None,
                    help="从这里拷 tokenizer 文件到输出目录（如 .../out-v6/adapter 或 .../cfg-vision）")
    a = ap.parse_args()
    if a.inspect:
        return inspect(a.gguf)
    if a.convert:
        if not a.out:
            print("--convert 需要 --out"); return 2
        return convert(a.gguf, a.out, a.cfg_json, a.max_shard_bytes, a.tokenizer_src)
    print("给 --inspect 或 --convert"); return 2


if __name__ == "__main__":
    sys.exit(main())
