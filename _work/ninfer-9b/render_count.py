# render_count.py — 用 artifact 同源模板 + tokenizer 复现 prompt，核对 serve(19/30/26) 与 CLI(25) 的 token 数
import json, sys, os
from jinja2 import Environment
from tokenizers import Tokenizer

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
TPL  = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\chat_template.jinja")
TOK  = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\tokenizer.json")

tpl = open(TPL, encoding="utf-8").read()
tok = Tokenizer.from_file(TOK)

def render(messages, gen=True):
    env = Environment(trim_blocks=False, lstrip_blocks=False)
    t = env.from_string(tpl)
    return t.render(messages=messages, add_generation_prompt=gen,
                    bos_token="", eos_token="",
                    enable_thinking=False, reasoning_effort="none")

cases = {
  "user-only":  [{"role":"user","content":"What is 2+2?"}],
  "system+user":[{"role":"system","content":"You are a helpful assistant."},
                 {"role":"user","content":"What is 2+2?"}],
  "essay":      [{"role":"user","content":"Write a 300-word essay about why local inference matters."}],
}
for name, msgs in cases.items():
    try:
        s = render(msgs)
    except Exception as e:
        print(f"[{name}] RENDER ERROR: {type(e).__name__}: {e}")
        continue
    ids = tok.encode(s, add_special_tokens=False).ids
    print(f"[{name}] chars={len(s)} tokens={len(ids)}")
    print("   first ids:", ids[:12], "... last ids:", ids[-8:])
    print("   text repr:", repr(s[-120:]))
print("\ntemplate bytes:", len(tpl.encode()))
