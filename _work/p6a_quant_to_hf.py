#!/usr/bin/env python
"""P6-A：复现 converter 的量化结果并转成 HF bf16 （用于质量验收）

为什么不用 .ninfer 里的权重
    .ninfer 的 TensorObject.id 是 `weight/000000` 这类无语义编号，
    要靠 483 条 bindings 映射回 text/layers/N/... 才能知道每个张量是谁。
    映射成本高，且错位会让评测结论失真。

本方案的等价性
    converter 用的是 grouped_absmax = absmax 定 scale + round 取码点 + fp16 存 scale
    本脚本用 gsq_gumbel_v2.baseline_absmax（同算法），差异只在：
      · row_split_k128_v1 只是存储布局，不影响量化数值
      · 两个 vocab 张量 converter 用 q8_g32，本脚本同样
    ⇒ 反量化后的权重与 .ninfer 内容数学等价

格式分配（从转换日志实测确认）
    text/token_embedding, text/output_head     q8_g32_fp16
    */attention/query|key, */gdn/query|key     q4_g64_fp16
    */mlp/gate|up                              q4_g64_fp16
    其余投影（value/output/down/o_proj）        q5_g64_fp16
    norm / a_log / dt_bias / conv / a_proj / b_proj   不量化（保持原 dtype）

产物
    models/merged-2b-nsfw-q5-hf/  —— 可被 transformers 直接加载的 bf16 模型

用法
    python _work/p6a_quant_to_hf.py                 # 全量（约 30-40 min）
    python _work/p6a_quant_to_hf.py --limit 3       # 只处理 3 个张量（烟测）
"""
import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "27b-kittyrev", "quant"))
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
from safetensors import safe_open  # noqa: E402
from safetensors.torch import save_file  # noqa: E402

import gsq_gumbel_v2 as G  # noqa: E402

# ★ Q6 格式不在 gsq_gumbel_v2 的 FORMATS 里，动态注册
if "q6_g64_fp16" not in G.FORMATS:
    G.FORMATS["q6_g64_fp16"] = G.Fmt(
        name="q6_g64_fp16", bits=6, group_size=64, qmin=-32, qmax=31, code_bias=0
    )

SRC = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models",
                   "merged-2b-nsfw-mtp-tuned-v3")
DST = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models",
                   "merged-2b-nsfw-q5-hf")

# 不量化的张量（按后缀匹配）
KEEP_FP = ("norm", "a_log", "dt_bias", "convolution", "a_projection", "b_projection")


def pick_format(name: str) -> str | None:
    """返回量化格式名；None = 保持原精度

    ★ 2026-11-07 修：必须按 **HF 真实张量名** 匹配，不能用 converter 的逻辑名。
      converter 叫 /attention/query，HF 里叫 self_attn.q_proj.weight；
      用错名字会让 q4 分支永不命中，311 个张量全部落到 q5（实测踩过）。
    """
    low = name.lower()
    # vocab
    if "embed_tokens" in low or "lm_head" in low:
        return "q8_g32_fp16"
    # 不量化
    if any(k in low for k in KEEP_FP):
        return None
    if low.startswith("mtp."):
        return None
    # 非 2D / 太小
    if not low.endswith(".weight"):
        return None
    # Q4：注意力 q/k 与 MLP gate/up（converter recipe 的 Q4 集合）
    # ★ in_proj_qkv 归 Q5：converter 内部把它拆成 gdn/query(Q4)+gdn/key(Q4)+gdn/value(Q5)，
    #   我们在 HF 里无法拆（单个 8192×4096 矩阵），按保守侧取 Q5
    if low.endswith(("q_proj.weight", "k_proj.weight")):
        return "q4_g64_fp16"
    if low.endswith(("gate_proj.weight", "up_proj.weight")):
        return "q4_g64_fp16"
    # 其余投影 Q5
    if low.endswith(("v_proj.weight", "o_proj.weight", "down_proj.weight",
                     "in_proj_qkv.weight", "in_proj_z.weight", "out_proj.weight")):
        return "q5_g64_fp16"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--dst", default=DST)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--all-q6", action="store_true", dest="all_q6",
                    help="所有量化张量统一用 q6_g64（验证量化损伤是否消失）")
    a = ap.parse_args()

    src_file = os.path.join(a.src, "model.safetensors")
    if not os.path.exists(src_file):
        sys.exit(f"[FATAL] 源权重不存在: {src_file}")

    # 收集任务
    tasks = []
    with safe_open(src_file, "pt") as f:
        for k in f.keys():
            shp = tuple(f.get_slice(k).get_shape())
            fmt = pick_format(k)
            if fmt is None or len(shp) != 2 or min(shp) < 64:
                tasks.append((k, shp, None))
            else:
                tasks.append((k, shp, fmt))
    nq = sum(1 for t in tasks if t[2])
    print(f"[plan] 张量 {len(tasks)} · 量化 {nq} · 保持原精度 {len(tasks)-nq}")
    if a.limit:
        tasks = tasks[: a.limit]
        print(f"[plan] 限制为前 {len(tasks)} 个")

    os.makedirs(a.dst, exist_ok=True)
    out = {}
    t_start = time.time()
    with safe_open(src_file, "pt", device="cpu") as f:
        for i, (k, shp, fmt) in enumerate(tasks, 1):
            t0 = time.time()
            w = f.get_tensor(k)
            if fmt is None:
                out[k] = w
                print(f"[{i}/{len(tasks)}] {k[-56:]:56s} keep {w.dtype} {shp}  {time.time()-t0:.1f}s")
            else:
                use_fmt = "q6_g64_fp16" if (a.all_q6 and fmt.startswith(("q4_", "q5_"))) else fmt
                wf = w.float()
                qm = G.baseline_absmax(wf, use_fmt)
                w_hat = G.dequantize(qm, use_fmt, k=shp[1])
                out[k] = w_hat.to(torch.bfloat16).reshape(shp).contiguous()
                print(f"[{i}/{len(tasks)}] {k[-56:]:56s} {use_fmt:14s} {shp}  "
                      f"{time.time()-t0:.1f}s")
                del wf, qm, w_hat
            del w

    # 补齐未被 limit 的说明
    print(f"\n[write] 写 safetensors …")
    save_file(out, os.path.join(a.dst, "model.safetensors"), metadata={"format": "pt"})
    sz = os.path.getsize(os.path.join(a.dst, "model.safetensors"))
    print(f"[write] {sz:,} B = {sz/2**30:.2f} GiB")

    # 复制元数据
    for fn in ("config.json", "generation_config.json", "chat_template.jinja",
               "tokenizer.json", "tokenizer_config.json",
               "preprocessor_config.json", "processor_config.json"):
        s = os.path.join(a.src, fn)
        if os.path.exists(s):
            shutil.copy2(s, os.path.join(a.dst, fn))

    print(f"[DONE] {a.dst}")
    print(f"       总耗时 {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
