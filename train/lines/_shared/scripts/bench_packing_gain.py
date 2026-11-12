# -*- coding: utf-8 -*-
"""bench_packing_gain.py —— packing 到底能提多少速（端到端 fwd+bwd）

对照：
  A 现状（packing=False）：pad 到本批最长 ⇒ 计算量 = N × max_len
  B 拼包：transformers 自己的 DataCollatorWithFlattening(return_flash_attn_kwargs=True,
    return_position_ids=True, return_seq_idx=True) ⇒ 计算量 = Σ len

注意：拼包必须走这个 collator（它同时给 cu_seq_lens_q/k、position_ids、seq_idx）。
手搓 cu_seq_lens 而漏 seq_idx 会让 dense attention / GDN 越界串样本 —— 实测差 1~3，
本脚本的正确性断言就是防这个。

用法：
    $env:PYTHONPATH='train\\scripts'
    train\\.venv\\Scripts\\python.exe train/lines/_shared/scripts/bench_packing_gain.py [batch] [reps]
"""
import os
import sys
import time

import torch
from transformers import DataCollatorWithFlattening

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import causal_conv1d as mine  # noqa: E402
from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5Config  # noqa: E402
from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM  # noqa: E402

SRC = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\base\Qwen3.8-27B"
LEN_PROFILE = [96, 128, 172, 172, 220, 320, 512, 900]      # 对齐 kitty 数据分布（p50≈172，长尾 900）


def build(hidden=1024, layers=6):
    cfg = Qwen3_5Config.from_pretrained(SRC)
    tc = cfg.text_config
    for k, v in dict(
        vocab_size=1024, hidden_size=hidden, intermediate_size=hidden * 4, num_hidden_layers=layers,
        num_attention_heads=8, num_key_value_heads=2, head_dim=128,
        linear_num_value_heads=8, linear_num_key_heads=4, linear_key_head_dim=64,
        linear_value_head_dim=64, linear_conv_kernel_dim=4, num_nextn_predict_layers=0,
        mtp_num_hidden_layers=0, pad_token_id=0, eos_token_id=1, bos_token_id=1,
        max_position_embeddings=8192,
    ).items():
        setattr(tc, k, v)
    tc.layer_types = ["full_attention" if (i + 1) % 4 == 0 else "linear_attention" for i in range(layers)]
    torch.manual_seed(0)
    return Qwen3_5ForCausalLM(tc).to("cuda", dtype=torch.bfloat16)


def pad_batch(seqs):
    L = max(s.numel() for s in seqs)
    ids = torch.zeros((len(seqs), L), dtype=torch.long, device="cuda")
    lab = torch.full((len(seqs), L), -100, dtype=torch.long, device="cuda")
    attn = torch.zeros((len(seqs), L), dtype=torch.long, device="cuda")
    for i, s in enumerate(seqs):
        n = s.numel()
        ids[i, :n] = s
        lab[i, :n] = s
        attn[i, :n] = 1
    return {"input_ids": ids, "labels": lab, "attention_mask": attn}


def pack_batch(seqs):
    coll = DataCollatorWithFlattening(return_flash_attn_kwargs=True,
                                      return_position_ids=True, return_seq_idx=True)
    b = coll([{"input_ids": s.cpu()} for s in seqs])
    return {k: (v.to("cuda") if torch.is_tensor(v) else v) for k, v in b.items()}


def step(model, batch):
    loss = model(**batch, use_cache=False).loss
    loss.backward()
    return loss.item()


def main():
    B = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    lens = (LEN_PROFILE * 4)[:B]
    print("torch", torch.__version__, "|", torch.cuda.get_device_name(0))
    print("batch=%d 长度=%s\n  Σ=%-5d  pad 后= %d×%d = %d  ⇒ 理论省掉 %.1f%% 计算"
          % (B, lens, sum(lens), B, max(lens), B * max(lens),
             100 * (1 - sum(lens) / (B * max(lens)))))

    model = build()
    mine._state["fwd_off"] = False
    mine._state["upd_off"] = True
    seqs = [torch.randint(0, 1024, (n,), device="cuda") for n in lens]

    # 正确性：以逐条单独前向为基准
    pb, kb = pad_batch(seqs), pack_batch(seqs)
    with torch.no_grad():
        solo = [model(input_ids=s.unsqueeze(0), use_cache=False).logits[0] for s in seqs]
        lo_pad = model(**{k: v for k, v in pb.items() if k != "labels"}, use_cache=False).logits
        lo_pk = model(**{k: v for k, v in kb.items() if k != "labels"}, use_cache=False).logits
    off = dpad = dpk = 0.0
    off = 0
    for i, n in enumerate(lens):
        dpad = max(dpad, (lo_pad[i, :n].float() - solo[i].float()).abs().max().item())
        dpk = max(dpk, (lo_pk[0, off:off + n].float() - solo[i].float()).abs().max().item())
        off += n
    print("  拼包正确性: padding 批 vs 单独 %.3e | 拼包 vs 单独 %.3e  (bf16 噪声级应 <1e-1)" % (dpad, dpk))

    for tag, batch in (("padding 批（现状）", pb), ("拼包（packing）", kb)):
        model.zero_grad(set_to_none=True)
        step(model, batch)                                        # warmup + 编译
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        losses = []
        for _ in range(REPS):
            model.zero_grad(set_to_none=True)
            losses.append(step(model, batch))
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / REPS
        gn = torch.sqrt(sum((p.grad.float() ** 2).sum() for p in model.parameters() if p.grad is not None))
        print("%-18s 步时 %7.1f ms | %6.1f 样本/s | %7.0f token/s | loss %.4f | grad_norm %.3f"
              % (tag, dt * 1000, B / dt, sum(lens) / dt, losses[-1], gn))
    _d = mine.diagnostics()
    print("\n诊断: fwd=%s varlen=%d 零拷贝=%d err=%s"
          % ("ref" if _d["fwd_off"] else "fla", _d["varlen_calls"], _d["zerocopy_hits"], _d["fwd_err"]))


if __name__ == "__main__":
    main()
