# -*- coding: utf-8 -*-
"""probe13: 模型级 decode 慢在哪 —— profiler 归因（参考路径 vs 替身路径）"""
import os, sys
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
os.environ.pop("CC1D_FLA_FWD", None); os.environ.pop("CC1D_FLA_UPDATE", None)
import torch
import causal_conv1d as mine
from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5Config
from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM

cfg = Qwen3_5Config.from_pretrained(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\base\Qwen3.8-27B")
tc = cfg.text_config
for k, v in dict(vocab_size=1024, hidden_size=1024, intermediate_size=2048, num_hidden_layers=4,
                 num_attention_heads=8, num_key_value_heads=2, head_dim=128,
                 linear_num_value_heads=8, linear_num_key_heads=4, linear_key_head_dim=64,
                 linear_value_head_dim=64, linear_conv_kernel_dim=4, num_nextn_predict_layers=0,
                 mtp_num_hidden_layers=0, pad_token_id=0, eos_token_id=1, bos_token_id=1,
                 max_position_embeddings=8192).items():
    setattr(tc, k, v)
tc.layer_types = ["linear_attention", "linear_attention", "linear_attention", "full_attention"]

torch.manual_seed(0)
model = Qwen3_5ForCausalLM(tc).to("cuda", dtype=torch.bfloat16).eval()

@torch.no_grad()
def run(use_fla, steps=8):
    mine._state["fwd_off"] = not use_fla
    mine._state["upd_off"] = not use_fla
    ids = torch.randint(0, 1024, (1, 16), device="cuda")
    out = model(input_ids=ids, use_cache=True)
    past = out.past_key_values
    nxt = out.logits[:, -1:].argmax(-1)
    torch.cuda.synchronize()
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as prof:
        for _ in range(steps):
            out = model(input_ids=nxt, past_key_values=past, use_cache=True)
            past = out.past_key_values
            nxt = out.logits[:, -1:].argmax(-1)
        torch.cuda.synchronize()
    ev = prof.key_averages()
    total = sum(e.self_device_time_total for e in ev)
    print(f"\n=== use_fla={use_fla}  总 CUDA {total/1000:.2f} ms / {steps} step = {total/1000/steps:.2f} ms/token ===")
    for e in sorted(ev, key=lambda x: -x.self_device_time_total)[:10]:
        if e.self_device_time_total > 0:
            print(f"  {e.key[:60]:60s} {e.self_device_time_total/1000:8.3f} ms  calls={e.count}")

run(False)
run(True)

print("\n=== prefill profiler（T=1024）===")
@torch.no_grad()
def run_prefill(use_fla):
    mine._state["fwd_off"] = not use_fla
    ids = torch.randint(0, 1024, (2, 1024), device="cuda")
    model(input_ids=ids, use_cache=False)
    torch.cuda.synchronize()
    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as prof:
        for _ in range(3):
            model(input_ids=ids, use_cache=False)
        torch.cuda.synchronize()
    ev = prof.key_averages()
    total = sum(e.self_device_time_total for e in ev)
    print(f"use_fla={use_fla}: 总 {total/1000:.2f} ms / 3 次 = {total/1000/3:.2f} ms/prefill")
    for e in sorted(ev, key=lambda x: -x.self_device_time_total)[:6]:
        if e.self_device_time_total > 0:
            print(f"  {e.key[:60]:60s} {e.self_device_time_total/1000:8.3f} ms calls={e.count}")

run_prefill(False)
run_prefill(True)
