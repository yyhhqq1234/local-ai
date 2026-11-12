# -*- coding: utf-8 -*-
"""bench_causal_conv1d_model.py —— 模型级 A/B：真 Qwen3_5(GDN) 网络里替身 vs 参考

不加载 27B 权重（12G 卡装不下），用真 config.json 缩成同架构小号网络、随机权重，
跑真实的 Qwen3_5GatedDeltaNet 前向（prefill）与带 cache 的逐 token decode，对照：
  · 参考路径 = 等价于"没装 causal_conv1d"的现状（transformers 的 torch 兜底）
  · 替身路径 = FLA kernel

同时给 **CUDA event 时间（GPU 真占用）** 和 **墙钟时间（含 CPU 派发）**：
小网络墙钟被 CPU 派发主导，看 GPU 时间才反映训练/推理收益。

用法：
    $env:PYTHONPATH='train\\scripts'
    train\\.venv\\Scripts\\python.exe train/lines/_shared/scripts/bench_causal_conv1d_model.py [T] [layers] [hidden]
"""
import os
import sys
import time

import torch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
import causal_conv1d as mine  # noqa: E402
from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5Config  # noqa: E402
from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM  # noqa: E402

SRC = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\base\Qwen3.8-27B"


def build(hidden=2048, layers=8, dtype=torch.bfloat16):
    cfg = Qwen3_5Config.from_pretrained(SRC)
    tc = cfg.text_config
    kw = dict(
        vocab_size=1024, hidden_size=hidden, intermediate_size=hidden * 4,
        num_hidden_layers=layers, num_attention_heads=8, num_key_value_heads=2, head_dim=128,
        linear_num_value_heads=16, linear_num_key_heads=8,
        linear_key_head_dim=128, linear_value_head_dim=128,
        linear_conv_kernel_dim=4, num_nextn_predict_layers=0, mtp_num_hidden_layers=0,
        pad_token_id=0, eos_token_id=1, bos_token_id=1, max_position_embeddings=8192,
    )
    for k, v in kw.items():
        setattr(tc, k, v)
    # 每 4 层一个 full attention（真模型是 full_attention_interval=4）
    tc.layer_types = ["full_attention" if (i + 1) % 4 == 0 else "linear_attention" for i in range(layers)]
    torch.manual_seed(0)
    return Qwen3_5ForCausalLM(tc).to("cuda", dtype=dtype).eval(), tc


def set_path(use_fla, use_upd=None):
    mine._state["fwd_off"] = not use_fla
    mine._state["upd_off"] = not (use_fla if use_upd is None else use_upd)
    mine._state["fwd_calls"] = 0
    mine._state["upd_calls"] = 0
    mine._state["zerocopy_hits"] = 0


@torch.no_grad()
def prefill_timed(model, ids, n=10):
    for _ in range(3):
        model(input_ids=ids, use_cache=False)
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(True), torch.cuda.Event(True)
    s.record()
    for _ in range(n):
        out = model(input_ids=ids, use_cache=False)
    e.record()
    torch.cuda.synchronize()
    gpu = s.elapsed_time(e) / n
    t0 = time.perf_counter()
    for _ in range(n):
        model(input_ids=ids, use_cache=False)
    torch.cuda.synchronize()
    wall = (time.perf_counter() - t0) / n * 1000
    return gpu, wall, out.logits


@torch.no_grad()
def decode_timed(model, ids, steps=16):
    out = model(input_ids=ids, use_cache=True)
    past, nxt = out.past_key_values, out.logits[:, -1:].argmax(-1)
    for _ in range(3):
        out = model(input_ids=nxt, past_key_values=past, use_cache=True)
        past, nxt = out.past_key_values, out.logits[:, -1:].argmax(-1)
    torch.cuda.synchronize()
    s, e = torch.cuda.Event(True), torch.cuda.Event(True)
    s.record()
    for _ in range(steps):
        out = model(input_ids=nxt, past_key_values=past, use_cache=True)
        past, nxt = out.past_key_values, out.logits[:, -1:].argmax(-1)
    e.record()
    torch.cuda.synchronize()
    gpu = s.elapsed_time(e) / steps
    t0 = time.perf_counter()
    for _ in range(steps):
        out = model(input_ids=nxt, past_key_values=past, use_cache=True)
        past, nxt = out.past_key_values, out.logits[:, -1:].argmax(-1)
    torch.cuda.synchronize()
    wall = (time.perf_counter() - t0) / steps * 1000
    return gpu, wall, out.logits


def main():
    T = int(sys.argv[1]) if len(sys.argv) > 1 else 2048
    layers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    hidden = int(sys.argv[3]) if len(sys.argv) > 3 else 2048
    print("torch", torch.__version__, "|", torch.cuda.get_device_name(0))
    model, tc = build(hidden, layers)
    conv_dim = tc.linear_num_key_heads * tc.linear_key_head_dim * 2 + tc.linear_num_value_heads * tc.linear_value_head_dim
    n_gdn = sum(1 for x in tc.layer_types if x == "linear_attention")
    print("小号网络: hidden=%d layers=%d GDN层=%d conv_dim=%d | prefill T=%d B=2"
          % (hidden, layers, n_gdn, conv_dim, T))
    ids = torch.randint(0, 1024, (2, T), device="cuda")

    rows = {}
    for tag, (fla, upd) in (("参考(现状)", (False, False)),
                            ("替身 fwd-only", (True, False)),
                            ("替身 fwd+update", (True, True))):
        set_path(fla, upd)
        g, w, lg = prefill_timed(model, ids)
        dg, dw, dlg = decode_timed(model, ids[:, :64])
        rows[tag] = (g, w, dg, dw, lg, dlg)
        print("%-16s prefill GPU %7.2f ms 墙钟 %7.2f | decode GPU %6.3f ms/token 墙钟 %6.2f | diag fwd=%d upd=%d 零拷贝=%d"
              % (tag, g, w, dg, dw, mine._state["fwd_calls"], mine._state["upd_calls"],
                 mine._state["zerocopy_hits"]))

    base = rows["参考(现状)"]
    print()
    for tag in ("替身 fwd-only", "替身 fwd+update"):
        g, w, dg, dw, lg, dlg = rows[tag]
        dl = (base[4].float() - lg.float()).abs()
        ddl = (base[5].float() - dlg.float()).abs()
        print("%-16s prefill 加速 GPU %5.2fx / 墙钟 %5.2fx | decode 加速 GPU %5.2fx / 墙钟 %5.2fx"
              % (tag, base[0] / g, base[1] / w, base[2] / dg, base[3] / dw))
        print("%-16s logits prefill max|diff|=%.3e mean=%.3e | decode max|diff|=%.3e | argmax 一致 %.4f/%.4f"
              % ("", dl.max().item(), dl.mean().item(), ddl.max().item(),
                 (base[4].argmax(-1) == lg.argmax(-1)).float().mean().item(),
                 (base[5].argmax(-1) == dlg.argmax(-1)).float().mean().item()))
    print("\n最终诊断:", mine.diagnostics())


if __name__ == "__main__":
    main()
