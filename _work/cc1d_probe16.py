# -*- coding: utf-8 -*-
"""probe16: 用 transformers 自己的 DataCollatorWithFlattening 走真拼包管线，
对照逐条单独前向，看 contamination 到底在谁身上（conv / GDN / dense attention）"""
import sys, torch
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
import causal_conv1d as mine
from transformers import DataCollatorWithFlattening
from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5Config
from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM

SRC = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\base\Qwen3.8-27B"

def build(layers=6, layer_types=None):
    cfg = Qwen3_5Config.from_pretrained(SRC)
    tc = cfg.text_config
    for k, v in dict(vocab_size=1024, hidden_size=1024, intermediate_size=4096, num_hidden_layers=layers,
                     num_attention_heads=8, num_key_value_heads=2, head_dim=128,
                     linear_num_value_heads=8, linear_num_key_heads=4, linear_key_head_dim=64,
                     linear_value_head_dim=64, linear_conv_kernel_dim=4, num_nextn_predict_layers=0,
                     mtp_num_hidden_layers=0, pad_token_id=0, eos_token_id=1, bos_token_id=1,
                     max_position_embeddings=8192).items():
        setattr(tc, k, v)
    tc.layer_types = layer_types or ["full_attention" if (i + 1) % 4 == 0 else "linear_attention" for i in range(layers)]
    torch.manual_seed(0)
    return Qwen3_5ForCausalLM(tc).to("cuda", dtype=torch.bfloat16).eval()

lens = [96, 128, 172, 220, 320]
seqs = [torch.randint(0, 1024, (n,)) for n in lens]

def report(tag, model):
    coll = DataCollatorWithFlattening(return_flash_attn_kwargs=True, return_position_ids=True, return_seq_idx=True)
    batch = coll([{"input_ids": s} for s in seqs])
    batch = {k: (v.to("cuda") if torch.is_tensor(v) else v) for k, v in batch.items()}
    with torch.no_grad():
        solo = [model(input_ids=s.unsqueeze(0).cuda(), use_cache=False).logits[0] for s in seqs]
        out = model(**batch, use_cache=False).logits
    off, worst = 0, 0.0
    for i, n in enumerate(lens):
        d = (out[0, off:off + n].float() - solo[i].float()).abs().max().item()
        worst = max(worst, d); off += n
    print(f"  {tag:34s} 拼包 vs 单独 max|diff| = {worst:.3e}   (batch keys: {sorted(batch)})")
    return worst

print("== A 全 GDN 层（无 dense attention）==")
report("全部 linear_attention", build(6, ["linear_attention"] * 6))
print("== B 混合（3 GDN + 1 dense，同 4 层）==")
report("混合 4 层", build(4))
print("== C 6 层（4 GDN + 2 dense）==")
report("混合 6 层", build(6))
print("== D 全 dense（对照）==")
report("全部 full_attention", build(4, ["full_attention"] * 4))
