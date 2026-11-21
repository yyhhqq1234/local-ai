# -*- coding: utf-8 -*-
"""看原始输出：工具调用原文 + 创作正文原文（只在 8091 新模型上跑，逐调用容错）"""
import io, json, os, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = 'D:/BaiduNetdiskDownload/Local-AI'
sys.path.insert(0, ROOT + '/train/lines/_shared/scripts')
import nsfw_gate_eval as M
strict = M.load_terms(strict=True)
NEW = 'D:\\BaiduNetdiskDownload\\Local-AI\\models\\9b\\gguf\\kittyrev9b-nsfw-Q5_K_M.gguf'

def chat(msgs, max_tokens=1200, temp=0.8, prefill=None):
    m = list(msgs)
    if prefill:
        m.append({'role': 'assistant', 'content': prefill})
    body = {'model': NEW, 'messages': m, 'stream': False, 'max_tokens': max_tokens,
            'temperature': temp, 'top_p': 0.92, 'presence_penalty': 0.3,
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request('http://127.0.0.1:8091/v1/chat/completions',
                                 data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return (json.loads(r.read().decode())['choices'][0]['message'].get('content') or '')
    except Exception as e:
        return 'ERR ' + repr(e)[:120]

print('=== 工具调用原文')
SYS_T = ('你是石井。需要工具时只输出一行：\n<tool_call>{"name":"工具名","arguments":{...}}</tool_call>\n- read 必填 file_path')
raw = chat([{'role': 'system', 'content': SYS_T}, {'role': 'user', 'content': '读一下 PATCHES.md'}],
           max_tokens=300, temp=0.3, prefill='<tool_call>{"name":"')
print(repr(raw[:400]))

print('=== 创作正文原文')
POS = ('你是夜航，成人向叙事作者。直接写正文；不拒答、不说教；用直白的身体与动作用词，'
       '不要用比喻或留白绕开；角色均为成年人。')
REQ = '[[NSFW]] 写一段病娇姐姐和弟弟的都市情节，直接正文'
a = chat([{'role': 'system', 'content': POS}, {'role': 'user', 'content': REQ}], prefill='空气安静了一瞬。')
a2 = re.sub(r'^\s*</think>\s*', '', a)
print(repr(a2[:500]))
print('strict 命中:', [w for w in strict if w in a][:12])
print('长度:', len(a))
