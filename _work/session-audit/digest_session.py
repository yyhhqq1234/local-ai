# -*- coding: utf-8 -*-
"""把会话 jsonl 压成时间线摘要：user 文本全文、assistant 文本前 400 字、tool 名+参数前 200 字"""
import sys, json

path = sys.argv[1]
outp = sys.argv[2] if len(sys.argv) > 2 else path + '.timeline.txt'
UMAX = int(sys.argv[3]) if len(sys.argv) > 3 else 4000

lines = [l for l in open(path, encoding='utf-8') if l.strip()]
out = []


def txt_of(msg):
    c = msg.get('content')
    if isinstance(c, str):
        return c
    parts = []
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict):
                if b.get('type') == 'text':
                    parts.append(b.get('text', ''))
                elif b.get('type') == 'tool-call':
                    parts.append('[TOOLCALL %s]' % json.dumps(b.get('toolName') or b.get('name'), ensure_ascii=False))
    return '\n'.join(parts)


for i, l in enumerate(lines):
    try:
        o = json.loads(l)
    except Exception:
        continue
    t = o.get('type')
    if t == 'turn/start':
        out.append('\n===== TURN START #%d =====' % len([x for x in out if x.startswith('\n===== TURN START')]) )
    elif t == 'user/message':
        m = o.get('message') or o
        s = txt_of(m)
        out.append('\n--- USER (line %d) ---\n%s' % (i, s[:UMAX]))
    elif t == 'assistant/message':
        m = o.get('message') or o
        s = txt_of(m)
        if s.strip():
            out.append('\n--- ASSISTANT (line %d) ---\n%s' % (i, s[:UMAX]))
    elif t == 'tool/call':
        name = o.get('toolName') or o.get('name') or (o.get('call') or {}).get('name')
        args = o.get('args') or o.get('input') or (o.get('call') or {}).get('args')
        a = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
        out.append('  [TOOL %s] %s' % (name, a[:300].replace('\n', ' ')))
    elif t == 'workspace/changes':
        out.append('  [WS-CHANGE] %s' % json.dumps(o, ensure_ascii=False)[:500])

open(outp, 'w', encoding='utf-8').write('\n'.join(out))
print('written %s  chars=%d' % (outp, sum(len(x) for x in out)))
