# -*- coding: utf-8 -*-
"""A2：把 NSFW LoRA（2b-nsfw-final）合并进 Qwen3.5-9B 基座，产出 HF 目录。

用法（在仓库根执行，venv 要带 torch/peft/transformers）：
  train/.venv/Scripts/python.exe _work/rebuild/merge_lora.py

产物：train/lines/9b-oxcoder/models/kittyrev-nsfw-merged/
说明：该 LoRA 原本训练于 OxCoder-9B；OxCoder 基座本地已删，
      这里直接叠到 Qwen3.5-9B —— 形状兼容，但会丢掉 OxCoder 的工具行为，只保留 NSFW 线。
"""
import os
import sys
import json

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

ROOT = r'D:\BaiduNetdiskDownload\Local-AI'
BASE = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder', 'models', 'Qwen3.5-9B')
ADAPTER = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder', 'out', '2b-nsfw-final')
OUT = os.path.join(ROOT, 'train', 'lines', '9b-oxcoder', 'models', 'kittyrev-nsfw-merged')

def main():
    for p, name in [(BASE, 'base'), (ADAPTER, 'adapter')]:
        if not os.path.isdir(p):
            print(f'[FAIL] 缺少 {name}: {p}')
            return 1
    print('[1/5] 读基座（bf16 / CPU）', flush=True)
    tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        BASE, torch_dtype=torch.bfloat16, device_map='cpu',
        low_cpu_mem_usage=True, trust_remote_code=True)
    print('[2/5] 挂 LoRA', flush=True)
    model = PeftModel.from_pretrained(model, ADAPTER, torch_dtype=torch.bfloat16)
    print('[3/5] merge_and_unload', flush=True)
    merged = model.merge_and_unload()
    print('[4/5] 保存', flush=True)
    os.makedirs(OUT, exist_ok=True)
    merged.save_pretrained(OUT, safe_serialization=True, max_shard_size='4GB')
    tok.save_pretrained(OUT)
    # 同步 chat template（训练时用的那份）
    tpl = os.path.join(ADAPTER, 'chat_template.jinja')
    if os.path.exists(tpl):
        with open(tpl, encoding='utf-8') as fh, open(os.path.join(OUT, 'chat_template.jinja'), 'w', encoding='utf-8') as out:
            out.write(fh.read())
    print('[5/5] 完成 ->', OUT, flush=True)
    idx = os.path.join(OUT, 'model.safetensors.index.json')
    if os.path.exists(idx):
        print('分片清单:', json.load(open(idx)).get('weight_map') is not None)
    return 0

if __name__ == '__main__':
    sys.exit(main())
