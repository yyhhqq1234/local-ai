"""hf_lm_loss.py —— 用 transformers 在 CPU 上直接算 merged 模型的 LM loss（判断权重是否真的可用）

判据：健康 27B 在中文/代码混合文本上 loss 应在 1.5-4；≈12.4（=ln 248320）说明输出接近均匀分布=权重坏了。
用法：python hf_lm_loss.py <model_dir> [n_samples]
"""
import json
import sys

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

d = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
tok = AutoTokenizer.from_pretrained(d, trust_remote_code=True)
print('[tok] vocab', tok.vocab_size, 'eos', tok.eos_token, 'pad', tok.pad_token)

texts = [
    "def add(a, b):\n    return a + b\n\n# 计算两数之和\n",
    "请用中文回答：反向工程中，判断一个函数是否为校验函数最可靠的特征是什么？",
    "<|im_start|>user\nhi<|im_end|>\n<|im_start|>assistant\nHello! How can I help you today?<|im_end|>\n",
]
texts = texts[:n]

from transformers import BitsAndBytesConfig
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                         bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
model, info = AutoModelForCausalLM.from_pretrained(d, quantization_config=bnb, dtype=torch.bfloat16,
                                             device_map={'': 0}, trust_remote_code=True,
                                             output_loading_info=True)
_mk = info.get('missing_keys') or []
_uk = info.get('unexpected_keys') or []
_bk = info.get('mismatched_keys') or []
print('[load-info] missing=%d unexpected=%d mismatched=%d' % (len(_mk), len(_uk), len(_bk)))
print('[load-info] missing sample', (info.get('missing_keys') or [])[:5])
print('[load-info] unexpected sample', (info.get('unexpected_keys') or [])[:5])
model.eval()
print('[load] ok, params %.2fB' % (sum(p.numel() for p in model.parameters()) / 1e9))

with torch.no_grad():
    for t in texts:
        ids = tok(t, return_tensors='pt').input_ids.to('cuda:0')
        out = model(input_ids=ids, labels=ids)
        print('[loss] len=%4d  loss=%.4f  ppl=%.1f' % (ids.shape[1], out.loss.item(), float(torch.exp(out.loss))))
