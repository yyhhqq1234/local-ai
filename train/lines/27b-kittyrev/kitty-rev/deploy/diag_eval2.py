#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""diag_eval2.py —— 补上 pick_checkpoint 的真实口径：kit_mod.SYS(229字) + kit_mod.TOOLS(4个)

目的：分离三个变量，确定「16 字符 / 0 pass」到底由哪个引起
  E1 真 SYS + TOOLS  + enable_thinking=False（= pick_checkpoint 现状）
  E2 真 SYS + None   + enable_thinking=False
  E3 真 SYS + TOOLS  + 训练口径手工拼接（不经 apply_chat_template 的 generation prompt）
"""
import importlib.util
import json
import sys

sys.path.insert(0, "/root/autodl-tmp/kitty-rev/kitty-rev/scripts")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import serve_4bit_base as serve

BASE = "/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B"
ADAPTER = "/root/autodl-tmp/kitty-rev/out/adapter-full3ep"
RE_EVAL = "/root/autodl-tmp/kitty-rev/kitty-rev/data/eval_re_extended.jsonl"
KIT = "/root/autodl-tmp/kitty-rev/kitty-rev/eval/eval_kitty.py"


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    k = load_mod(KIT, "kx")
    SYS, TOOLS = k.SYS, k.TOOLS
    print(f"[kit] SYS={len(SYS)} chars  TOOLS={len(TOOLS)}")

    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token_id = tok.eos_token_id
    model = AutoModelForCausalLM.from_pretrained(
        BASE, quantization_config=bnb, device_map={"": 0},
        dtype=torch.bfloat16, trust_remote_code=True)
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, ADAPTER).eval()

    rows = [json.loads(l) for l in open(RE_EVAL, encoding="utf-8")][:2]

    def run(tag, p, ctx, max_new=256):
        ids_full = tok(p, return_tensors="pt", add_special_tokens=False).input_ids
        ids = ids_full[:, :ctx].cuda()
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id,
                                 eos_token_id=tok.eos_token_id)
        raw = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=False)
        txt = serve.strip_specials(tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))
        n_new = int(out.shape[1] - ids.shape[1])
        print(f"  [{tag}] prompt_tok={ids_full.shape[1]} used={ids.shape[1]} "
              f"trunc={ids.shape[1] < ids_full.shape[1]} out_tok={n_new} out_chars={len(txt)}")
        print(f"     tail_of_prompt={p[-70:]!r}")
        print(f"     TEXT>>> {txt!r}")
        return txt

    for idx, r in enumerate(rows, 1):
        msgs = [{"role": "system", "content": SYS}] + r["messages"]
        print(f"\n===== sample {idx} cat={r.get('meta',{}).get('cat')} =====")

        p_e1 = serve.build_prompt(tok, msgs, TOOLS, False, "medium")
        run("E1 真SYS+TOOLS+think=False ctx512", p_e1, 512)
        run("E1b 同一 prompt ctx=4096", p_e1, 4096)

        p_e2 = serve.build_prompt(tok, msgs, None, False, "medium")
        run("E2 真SYS+无TOOLS ctx512", p_e2, 512)

        # E3 训练口径：完整对话模板 + 手工补 assistant 起始（不注入空 think 块）
        body = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
        marker = "<|im_start|>assistant\n"
        p_e3 = body.split(marker)[0] + marker if marker in body else body + marker
        run("E3 训练口径(手工assistant头) ctx512", p_e3, 512)


if __name__ == "__main__":
    main()
