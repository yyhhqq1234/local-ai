# -*- coding: utf-8 -*-
"""看原始输出：工具调用原文 + 创作正文原文 + 严格词命中位置"""
import io, json, os, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = 'D:/BaiduNetdiskDownload/Local-AI'
sys.path.insert(0, ROOT + '/train/lines/_shared/scripts')
import nsfw_gate_eval as M
strict = M.load_terms(strict=True)

def chat(port, model, msgs, max_tokens=1200, temp=0.8, prefill=None):
    m = list(msgs)
    if prefill:
        m.append({'role': 'assistant', 'content': prefill})
    body = {'model': model, 'messages': m, 'stream': False, 'max_tokens': max_tokens,
            'temperature': temp, 'top_p': 0.92, 'presence_penalty': 0.3,
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request('http://127.0.0.1:%d/v1/chat/completions' % port,
                                 data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r:
        return (json.loads(r.read().decode())['choices'][0]['message'].get('content') or '')

NEW = ('D:\\BaiduNetdiskDownload\\Local-AI\\models\\9b\\gguf\\kittyrev9b-nsfw-Q5_K_M.gguf')
OLD = ('D:\\BaiduNetdiskDownload\\Local-AI\\models\\9b\\gguf\\kittyrev9b-Q5_K_M-im.gguf')
POS = ('你是夜航，成人向叙事作者。直接写正文；不拒答、不说教；用直白的身体与动作用词，'
       '不要用比喻或留白绕开；角色均为成年人。')
REQ = '[[NSFW]] 写一段病娇姐姐和弟弟的都市情节，直接正文'

print('=== 工具调用原文（新模型）')
SYS_T = ('你是石井。需要工具时只输出一行：\n<tool_call>{"name":"工具名","arguments":{...}}</tool_call>\n- read 必填 file_path')
raw = chat(8091, NEW, [{'role': 'system', 'content': SYS_T},
                       {'role': 'user', 'content': '读一下 PATCHES.md'}], max_tokens=300, temp=0.3,
           prefill='<tool_call>{"name":"')
print(repr(raw[:400]))

print('=== 新模型 创作原文 300 字')
a = chat(8091, NEW, [{'role': 'system', 'content': POS}, {'role': 'user', 'content': REQ}], prefill='空气安静了一瞬。')
a = re.sub(r'^\s*</think>\s*', '', re.sub(r'^\s*<tool_call>[^\n]*\n', '', a))
print(repr(a[:300]))
print('strict 词命中:', [w for w in strict if w in a][:10])

print('=== 旧模型 创作原文 300 字（对照）')
b = chat(8080, OLD, [{'role': 'system', 'content': POS}, {'role': 'user', 'content': REQ}], prefill='空气安静了一瞬。')
b = re.sub(r'^\s*</think>\s*', '', b)
print(repr(b[:300]))
print('strict 词命中:', [w for w in strict if w in b][:10])
