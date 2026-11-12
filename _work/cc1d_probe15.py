# -*- coding: utf-8 -*-
"""probe15: decode 逐步对账（FLA update 在哪一步开始偏）"""
import sys, torch
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
import causal_conv1d as mine
from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5Config
from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM

cfg = Qwen3_5Config.from_pretrained(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\base\Qwen3.8-27B")
tc = cfg.text_config
for k, v in dict(vocab_size=1024, hidden_size=512, intermediate_size=1024, num_hidden_layers=4,
                 num_attention_heads=8, num_key_value_heads=2, head_dim=128,
                 linear_num_value_heads=8, linear_num_key_heads=4, linear_key_head_dim=64,
                 linear_value_head_dim=64, linear_conv_kernel_dim=4, num_nextn_predict_layers=0,
                 mtp_num_hidden_layers=0, pad_token_id=0, eos_token_id=1, bos_token_id=1,
                 max_position_embeddings=4096).items():
    setattr(tc, k, v)
tc.layer_types = ["linear_attention", "linear_attention", "linear_attention", "full_attention"]
torch.manual_seed(0)
model = Qwen3_5ForCausalLM(tc).to("cuda", dtype=torch.bfloat16).eval()

IDS = torch.randint(0, 1024, (1, 16), device="cuda")

@torch.no_grad()
def decode_logits(use_upd, steps=6):
    mine._state["fwd_off"] = False
    mine._state["upd_off"] = not use_upd
    ids = IDS
    out = model(input_ids=ids, use_cache=True)
    past, nxt = out.past_key_values, out.logits[:, -1:].argmax(-1)
    seq = [out.logits[:, -1:].clone()]
    for _ in range(steps):
        out = model(input_ids=nxt, past_key_values=past, use_cache=True)
        past, nxt = out.past_key_values, out.logits[:, -1:].argmax(-1)
        seq.append(out.logits[:, -1:].clone())
    return seq

a = decode_logits(False)
b = decode_logits(True)
print("step  max|diff|   mean|diff|   ref_argmax  fla_argmax")
for i, (x, y) in enumerate(zip(a, b)):
    d = (x.float() - y.float()).abs()
    print(f"{i:4d}  {d.max().item():.4e}  {d.mean().item():.3e}   {int(x.argmax(-1)):8d}  {int(y.argmax(-1)):8d}")
