#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""diag_eval.py —— 判清「re_pass=0/60 + 16 字符输出」是能力问题还是评测口径问题

假设 H3（主）：pick_checkpoint.py 的 --ctx 默认 512，`ids[:, :a.ctx]` 把
  system(SYS 很长) + tools + user 一起截掉，模型只看到半句 → 立即 EOS → 16 字符。
对照 H1：训练侧 add_generation_prompt=False vs 评测侧 True（格式口径）
对照 H2：tools 参数导致模型倾向短 tool_call

输出四组实验 + train 侧 assistant 前 20 token。
"""
import json
import sys
import time

sys.path.insert(0, "/root/autodl-tmp/kitty-rev/kitty-rev/scripts")

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
import serve_4bit_base as serve

BASE = "/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B"
ADAPTER = "/root/autodl-tmp/kitty-rev/out/adapter-full3ep"
RE_EVAL = "/root/autodl-tmp/kitty-rev/kitty-rev/data/eval_re_extended.jsonl"
TRAIN = "/root/autodl-tmp/kitty-rev/kitty-rev/data/subsets/re-subset.train.jsonl"

# 与 pick_checkpoint 保持一致的 system 提示来源
try:
    import kitty_mod  # noqa
    SYS = kitty_mod.SYS
except Exception:
    SYS = "You are a reverse-engineering assistant."


def main():
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token_id = tok.eos_token_id
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        BASE, quantization_config=bnb, device_map={"": 0},
        dtype=torch.bfloat16, trust_remote_code=True)
    from peft import PeftModel
    model = PeftModel.from_pretrained(model, ADAPTER).eval()
    print(f"[load] {time.time()-t0:.1f}s vram={torch.cuda.memory_allocated()/2**30:.2f} GiB")

    rows = [json.loads(l) for l in open(RE_EVAL, encoding="utf-8")][:2]

    def gen(msgs, tools, ctx, max_new=256):
        p = serve.build_prompt(tok, msgs, tools, False, "medium")
        full = tok(p, return_tensors="pt", add_special_tokens=False).input_ids
        n_full = full.shape[1]
        ids = full[:, :ctx].cuda()
        n_used = ids.shape[1]
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=max_new, do_sample=False,
                                 pad_token_id=tok.pad_token_id,
                                 eos_token_id=tok.eos_token_id)
        raw = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=False)
        txt = serve.strip_specials(tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))
        return dict(prompt_chars=len(p), prompt_tokens=n_full, used_tokens=n_used,
                    truncated=(n_used < n_full), out_chars=len(txt),
                    out_tokens=int(out.shape[1] - n_used),
                    has_im_end=("<|im_end|>" in raw), text=txt, raw_tail=raw[-40:])

    for idx, r in enumerate(rows, 1):
        msgs = [{"role": "system", "content": SYS}] + r["messages"]
        print(f"\n===== sample {idx}  cat={r.get('meta',{}).get('cat')} =====")
        print(f"  user 提问前 80 字: {r['messages'][0]['content'][:80]!r}")

        for tag, tools, ctx in (
            ("A ctx=512  tools=None", None, 512),
            ("B ctx=4096 tools=None", None, 4096),
            ("C ctx=4096 tools=[]", [], 4096),
            ("D ctx=8192 tools=None", None, 8192),
        ):
            g = gen(msgs, tools, ctx)
            print(f"  [{tag}] prompt tok={g['prompt_tokens']} used={g['used_tokens']} "
                  f"trunc={g['truncated']} out_tok={g['out_tokens']} out_chars={g['out_chars']} "
                  f"im_end={g['has_im_end']}")
            print(f"     TEXT>>> {g['text']!r}")

    # train 侧 assistant 段开头 20 token
    print("\n===== train 侧 assistant 段 token 实证 =====")
    tr = json.loads(open(TRAIN, encoding="utf-8").readline())
    msgs = tr["messages"]
    full = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
    pre = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True)
    pre_ids = tok(pre, add_special_tokens=False).input_ids
    full_ids = tok(full, add_special_tokens=False).input_ids
    ans_ids = full_ids[len(pre_ids):]
    print("  add_generation_prompt=True 前缀 tok 数:", len(pre_ids))
    print("  完整对话 tok 数:", len(full_ids), "→ assistant span tok 数:", len(ans_ids))
    print("  assistant 前 20 token 解码:", repr(tok.decode(ans_ids[:20])))
    print("  assistant span 是否含 <|im_end|>:", "<|im_end|>" in tok.decode(ans_ids))
    print("  评测 prompt 尾部 40 字:", repr(tok.decode(tok(serve.build_prompt(
        tok, [{"role": "system", "content": SYS}] + msgs[:-1], None, False, "medium"),
        add_special_tokens=False).input_ids[-40:])))
    print("  训练 prompt 尾部 40 字:", repr(tok.decode(pre_ids[-40:])))


if __name__ == "__main__":
    main()
