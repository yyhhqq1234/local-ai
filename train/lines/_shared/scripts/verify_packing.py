# -*- coding: utf-8 -*-
"""verify_packing.py —— packing=True 端到端验收（causal_conv1d varlen 是否真把序列切开）

场景：3 条不等长样本拼成一条 (1, total)，position_ids 复位、cu_seq_lens_q 随 batch 下发
（这正是 transformers 的 DataCollatorWithFlattening(return_flash_attn_kwargs=True) 产物）。

判据：
  A 有 varlen（cu_seq_lens_q 生效）→ 拼包 logits 与"逐条单独跑"一致（bf16 舍入级）
  B 关掉 varlen（模拟没有 causal_conv1d 的老状态）→ 拼包 logits 明显偏离，证明边界真的被切开
"""
import os
import sys

import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import causal_conv1d as mine  # noqa: E402
from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5Config  # noqa: E402
from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM  # noqa: E402

SRC = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\base\Qwen3.8-27B"


def build(hidden=512, layers=4):
    cfg = Qwen3_5Config.from_pretrained(SRC)
    tc = cfg.text_config
    for k, v in dict(
        vocab_size=1024, hidden_size=hidden, intermediate_size=hidden * 2, num_hidden_layers=layers,
        num_attention_heads=8, num_key_value_heads=2, head_dim=128,
        linear_num_value_heads=8, linear_num_key_heads=4, linear_key_head_dim=64,
        linear_value_head_dim=64, linear_conv_kernel_dim=4, num_nextn_predict_layers=0,
        mtp_num_hidden_layers=0, pad_token_id=0, eos_token_id=1, bos_token_id=1,
        max_position_embeddings=4096,
    ).items():
        setattr(tc, k, v)
    tc.layer_types = ["linear_attention", "linear_attention", "linear_attention", "full_attention"][:layers]
    torch.manual_seed(0)
    return Qwen3_5ForCausalLM(tc).to("cuda", dtype=torch.bfloat16).eval()


@torch.no_grad()
def run_packed(model, seqs, use_varlen):
    lens = [s.numel() for s in seqs]
    ids = torch.cat(seqs).unsqueeze(0)
    pos = torch.cat([torch.arange(n, device="cuda") for n in lens]).unsqueeze(0)
    cu_list = [0] + list(torch.cumsum(torch.tensor(lens), 0).tolist())
    cu = torch.tensor(cu_list, dtype=torch.int32, device="cuda")   # collator 出来的就是 int32 张量
    if use_varlen:
        out = model(input_ids=ids, position_ids=pos, cu_seq_lens_q=cu, cu_seq_lens_k=cu, use_cache=False)
    else:
        # 不给 cu_seqlens：卷积按整条拼包算，等价于"没有 causal_conv1d"
        old = mine._state["fwd_off"]
        mine._state["fwd_off"] = True
        try:
            out = model(input_ids=ids, position_ids=pos, use_cache=False)
        finally:
            mine._state["fwd_off"] = old
    return out.logits, cu_list


@torch.no_grad()
def run_separate(model, seqs):
    outs = []
    for s in seqs:
        o = model(input_ids=s.unsqueeze(0), use_cache=False)
        outs.append(o.logits)
    return outs


def main():
    torch.manual_seed(1)
    model = build()
    lens = [40, 55, 33]
    seqs = [torch.randint(0, 1024, (n,), device="cuda") for n in lens]
    print("样本长度", lens, "| 拼包总长", sum(lens), "| 模型 hidden=512 4层(3 GDN)")

    sep = run_separate(model, seqs)
    mine._state["fwd_off"] = False
    pk, cu = run_packed(model, seqs, use_varlen=True)
    print("varlen 调用计数:", mine.diagnostics()["varlen_calls"])
    dmax = 0.0
    for i, (s, e) in enumerate(zip(cu[:-1], cu[1:])):
        d = (pk[:, s:e].float() - sep[i].float()).abs()
        dmax = max(dmax, d.max().item())
        print(f"  seg{i} len={e-s:3d} 拼包 vs 单独  max|diff|={d.max().item():.3e} mean={d.mean().item():.3e} "
              f"argmax 一致 {(pk[:, s:e].argmax(-1) == sep[i].argmax(-1)).float().mean().item():.4f}")

    naive, _ = run_packed(model, seqs, use_varlen=False)
    dn = max((naive[:, s:e].float() - sep[i].float()).abs().max().item()
             for i, (s, e) in enumerate(zip(cu[:-1], cu[1:])))
    print(f"\n不切边界（等价没装 causal_conv1d）: max|diff|={dn:.3e}")

    ok = dmax <= 0.15 and dn > 3 * dmax
    print("\n结果:", "PASS —— varlen 生效，packing 可用" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
