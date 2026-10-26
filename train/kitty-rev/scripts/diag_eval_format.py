#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""diag_eval_format.py —— 诊断 eval_re 0/60 的根因：训练侧与评测侧的 prompt 格式是否一致

在云端跑（需 GPU）。输出四组对照，打印**生成原文**而不是摘要。

用法：
  python diag_eval_format.py --base base/Qwen3.8-27B --adapter out/adapter-full3ep
"""
import argparse
import json

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter", default="")
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--ctx", type=int, default=2048)
    a = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(a.base, trust_remote_code=True)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(
        a.base, quantization_config=bnb, dtype=torch.bfloat16,
        device_map={"": 0}, trust_remote_code=True)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
        print(f"[adapter] {a.adapter}")
    model.eval()

    msgs = [{"role": "user", "content": "`dump` 是哪个 kitty 工具的 action？直接给答案。"}]

    def render(**kw):
        try:
            return tok.apply_chat_template(msgs, tokenize=False, **kw)
        except Exception as e:
            return f"<<ERR {type(e).__name__}: {e}>>"

    variants = {
        "A 训练口径（add_generation_prompt=False）": dict(add_generation_prompt=False),
        "B 评测口径（True + enable_thinking=False）": dict(add_generation_prompt=True, enable_thinking=False),
        "C 评测口径+thinking（True + enable_thinking=True）": dict(add_generation_prompt=True, enable_thinking=True),
        "D 裸 True（不传 enable_thinking）": dict(add_generation_prompt=True),
    }

    print("=" * 70)
    print("第一部分：四种 chat_template 渲染的**尾部 200 字符**（看 assistant 段开头长什么样）")
    print("=" * 70)
    for name, kw in variants.items():
        s = render(**kw)
        print(f"\n--- {name} ---")
        print(f"  总长 {len(s)} 字符")
        print(f"  尾部: {s[-200:]!r}")

    print("\n" + "=" * 70)
    print("第二部分：用 B（评测口径）生成，打印原文")
    print("=" * 70)
    for name in ["B 评测口径（True + enable_thinking=False）", "D 裸 True（不传 enable_thinking）"]:
        kw = variants[name]
        text = render(**kw)
        ids = tok(text, return_tensors="pt", truncation=True, max_length=a.ctx).to(model.device)
        with torch.no_grad():
            out = model.generate(**ids, max_new_tokens=a.max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        gen = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=False)
        print(f"\n--- {name} ---")
        print(f"  prompt_token={ids['input_ids'].shape[1]}  generated_token={out.shape[1]-ids['input_ids'].shape[1]}")
        print(f"  原文(repr): {gen[:400]!r}")

    print("\n" + "=" * 70)
    print("第三部分：训练数据里 assistant 段的开头 40 个 token（对齐检查）")
    print("=" * 70)
    try:
        with open("kitty-rev/data/subsets/re-subset.train.jsonl", encoding="utf-8") as f:
            row = json.loads(f.readline())
        full = tok.apply_chat_template(row["messages"], tokenize=False, add_generation_prompt=False)
        ids_full = tok(full, add_special_tokens=False)["input_ids"]
        # 找 assistant 段起点：用最后一条 assistant 内容反查
        ans = row["messages"][-1]["content"][:30]
        idx = full.rfind(ans[:15])
        if idx > 0:
            pre_ids = tok(full[:idx], add_special_tokens=False)["input_ids"]
            print(f"  assistant 内容起点 char_offset={idx}")
            print(f"  该位置前 {len(pre_ids)} 个 token")
            print(f"  assistant 段开头 40 token 解码: {tok.decode(ids_full[len(pre_ids):len(pre_ids)+40])!r}")
        else:
            print("  [warn] 没找到 assistant 段起点")
    except Exception as e:
        print(f"  [skip] {e}")


if __name__ == "__main__":
    main()
