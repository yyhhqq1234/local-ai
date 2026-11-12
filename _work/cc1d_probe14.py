# -*- coding: utf-8 -*-
"""probe14: 模型里 conv_state / 输入的 dtype 与 stride（FLA update 在模型内为何算错）"""
import sys, torch
sys.path.insert(0, r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\scripts")
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
print("mamba_ssm_dtype =", getattr(tc, "mamba_ssm_dtype", "?"))
torch.manual_seed(0)
m = Qwen3_5ForCausalLM(tc).to("cuda", dtype=torch.bfloat16).eval()

with torch.no_grad():
    out = m(input_ids=torch.randint(0, 1024, (1, 8), device="cuda"), use_cache=True)
    cache = out.past_key_values
    for i, lay in enumerate(cache.layers):
        if getattr(lay, "conv_states", None) is not None:
            cs = lay.conv_states[0]
            print(f"layer{i} conv_state dtype={cs.dtype} shape={tuple(cs.shape)} stride={cs.stride()} contig={cs.is_contiguous()}")
        else:
            print(f"layer{i} 无 conv_states (full attention)")
    print("recurrent_states dtype:", [ (l.recurrent_states[0].dtype if getattr(l,'recurrent_states',None) else None) for l in cache.layers])

    # 单步 update 的真实张量
    lin = m.model.layers[0].linear_attn
    hs = torch.randn(1, 8, tc.hidden_size, device="cuda", dtype=torch.bfloat16)
    mixed = lin.in_proj_qkv(hs).transpose(1, 2)
    print("\nmixed_qkv dtype", mixed.dtype, "shape", tuple(mixed.shape), "stride", mixed.stride())
    st = cache.layers[0].conv_states[0]
    print("conv_state dtype", st.dtype)
