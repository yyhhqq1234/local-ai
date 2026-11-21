# -*- coding: utf-8 -*-
"""长上下文召回验证（needle-in-haystack）：确认 32K/64K/128K/256K 真能用，不是"能起服务但读不到内容"

用法:
  python _work/quant/verify_longctx.py --port 8095 --model <gguf> --ctx 262144
判据: 每个深度（10%/50%/90%）都能召回 needle 串；任一失败 = 该档上下文不可用
"""
import argparse
import io
import json
import os
import random
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def build_haystack(n_chars, needle, depth):
    """用中性填充语把 needle 埋到指定深度（约等于 tokens/1.3）"""
    filler = ('工作区日志片段：接口返回 200，字段齐全，校验通过；下一条记录继续。\n')
    per = len(filler)
    n_before = int(n_chars * depth / per)
    n_after = int(n_chars * (1 - depth) / per)
    return filler * n_before + '【关键标记】' + needle + '\n' + filler * n_after


def ask(port, model, prompt, max_tokens=64):
    body = {'model': model,
            'messages': [{'role': 'user', 'content': prompt + '\n\n只回答标记串本身，不要解释。'}],
            'max_tokens': max_tokens, 'temperature': 0, 'stream': False,
            'chat_template_kwargs': {'enable_thinking': False}}
    req = urllib.request.Request('http://127.0.0.1:%d/v1/chat/completions' % port,
                                 data=json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read().decode())
    return (d['choices'][0]['message'].get('content') or ''), round(time.time() - t0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8095)
    ap.add_argument('--model', required=True)
    ap.add_argument('--ctx', type=int, default=262144)
    ap.add_argument('--depths', default='0.1,0.5,0.9')
    a = ap.parse_args()

    # 目标正文长度 ≈ ctx * 1.3 字符 - 预留输出
    budget_chars = int(a.ctx * 1.3 * 0.85)
    needle = 'K7-QX-%04d' % random.randint(1000, 9999)
    print('== 长上下文召回：ctx=%d，正文约 %d 字符，needle=%s' % (a.ctx, budget_chars, needle))
    ok = 0
    total = 0
    for d in [float(x) for x in a.depths.split(',')]:
        text = build_haystack(budget_chars, needle, d)
        prompt = ('下面是一段很长的日志。请找出其中被【关键标记】标注的字符串并原样输出。\n\n' + text +
                  '\n\n问题：【关键标记】后面那串字符串是什么？')
        total += 1
        try:
            out, sec = ask(a.port, a.model, prompt)
        except Exception as e:
            print('  depth=%.0f%% 请求失败: %s' % (d * 100, str(e)[:120]))
            continue
        hit = needle in out
        ok += 1 if hit else 0
        print('  depth=%3.0f%%  %s  %5.1fs  out=%r' % (d * 100, 'HIT ' if hit else 'MISS', sec, out.strip()[:40]))
    print('== 召回 %d/%d → %s' % (ok, total, 'PASS' if ok == total else 'FAIL（该档上下文不可用）'))
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
