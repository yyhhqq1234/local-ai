# -*- coding: utf-8 -*-
"""弄清 2b-nsfw-final 到底学了什么：读训练样本对 + 用训练格式探测"""
import io, json, os, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = 'D:/BaiduNetdiskDownload/Local-AI'
DATA = ROOT + '/train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated-v5.jsonl'
NEW = 'D:\\BaiduNetdiskDownload\\Local-AI\\models\\9b\\gguf\\kittyrev9b-nsfw-Q5_K_M.gguf'

samples = []
with io.open(DATA, encoding='utf-8', errors='replace') as fh:
    for line in fh:
        try:
            o = json.loads(line)
        except Exception:
            continue
        msgs = o.get('messages') or []
        sysm = next((m.get('content') for m in msgs if m.get('role') == 'system'), '')
        u = next((m.get('content') for m in msgs if m.get('role') == 'user'), '')
        a = next((m.get('content') for m in msgs if m.get('role') == 'assistant'), '')
        for k, v in (('sys', sysm), ('u', u), ('a', a)):
            if isinstance(v, list):
                pass
        samples.append((sysm, u, a))
print('样本数', len(samples))
for i in (0, 1, 2):
    s, u, a = samples[i]
    print(f'--- 样本{i}')
    print(' SYS:', repr(str(s)[:160]))
    print(' USER:', repr(str(u)[:160]))
    print(' ASST:', repr(str(a)[:300]))

def chat(sysmsg, user, max_tokens=800, temp=0.6):
    body = {'model': NEW, 'messages': [{'role': 'system', 'content': sysmsg}, {'role': 'user', 'content': user}],
            'stream': False, 'max_tokens': max_tokens, 'temperature': temp, 'top_p': 0.92,
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request('http://127.0.0.1:8091/v1/chat/completions',
                                 data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r:
        return (json.loads(r.read().decode())['choices'][0]['message'].get('content') or '')

s0, u0, a0 = samples[0]
print('=== 用训练样本的 system+user 复现')
out = chat(str(s0), str(u0))
print(repr(out[:500]))
