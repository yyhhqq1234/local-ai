# count_prompts.py — 用同源模板+tokenizer 复算各提示词的 prompt token 数
import os
from jinja2 import Environment
from tokenizers import Tokenizer

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
TPL  = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\chat_template.jinja")
TOK  = os.path.join(ROOT, r"train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3\tokenizer.json")
tpl = open(TPL, encoding="utf-8").read()
tok = Tokenizer.from_file(TOK)
env = Environment(trim_blocks=False, lstrip_blocks=False)

def count(msgs):
    s = env.from_string(tpl).render(messages=msgs, add_generation_prompt=True,
        bos_token="", eos_token="", enable_thinking=False, reasoning_effort="none")
    return len(tok.encode(s, add_special_tokens=False).ids)

ok_prompts = [
 'What is 2+2?',
 'What is the capital of France?',
 'Name three colors.',
 'Write a haiku about rain.',
 'Explain what a transformer is in one paragraph.',
 'What is 17 * 3?',
 'List two differences between TCP and UDP.',
 'Write a Python function that returns the factorial of n.',
]
bad_prompts = [
 'Write a 300-word essay about why local inference matters.',
]
print("== 正常组 ==")
for p in ok_prompts:
    print(f"  {count([{'role':'user','content':p}]):3d}  {p}")
print("== 退化组 ==")
for p in bad_prompts:
    print(f"  {count([{'role':'user','content':p}]):3d}  {p}")
print(f"  {count([{'role':'system','content':'You are a helpful assistant.'},{'role':'user','content':'What is 2+2?'}]):3d}  [system]+What is 2+2?")
print(f"  {count([{'role':'system','content':'You are 石井, a terse assistant.'},{'role':'user','content':'What is 2+2?'}]):3d}  [system-zh]+What is 2+2?")
