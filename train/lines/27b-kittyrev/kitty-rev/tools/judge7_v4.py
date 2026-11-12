#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""judge7_v4.py —— 判据七：引擎实问，验可读中文（字数/中文占比/无乱码/思考已关）"""
import json, sys, urllib.request

URL = "http://127.0.0.1:1234/v1/chat/completions"
Q = ("请用中文简要说明：Windows PE 文件里 FileAlignment（通常 0x200）和 SectionAlignment（通常 0x1000）"
     "有什么区别？为什么节表里的 VirtualAddress 要按 0x1000 对齐，而文件里的 PointerToRawData 按 0x200 对齐？"
     "回答控制在 150 字以内。")


def ask(q, max_tokens=600):
    body = json.dumps({
        "model": "qwen3.8-27b-ablit-swift15-iq2s",
        "messages": [{"role": "user", "content": q}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main():
    try:
        d = ask(Q)
    except Exception as e:
        print(f"[G7] FAIL 请求失败: {e}")
        return 1
    ch = d["choices"][0]
    msg = ch.get("message", {})
    content = (msg.get("content") or "").strip()
    reasoning = msg.get("reasoning_content") or ""
    usage = d.get("usage", {})
    rt = usage.get("reasoning_tokens")
    if rt is None:
        rt = usage.get("completion_tokens_details", {}).get("reasoning_tokens", 0)

    n = len(content)
    cjk = sum(1 for c in content if "\u4e00" <= c <= "\u9fff")
    ratio = cjk / max(n, 1)
    # 乱码特征：连续 3 个以上非 ASCII 且非中文/非常见标点
    def is_bad(c):
        o = ord(c)
        if o < 128:
            return False
        if "\u4e00" <= c <= "\u9fff":
            return False
        if c in "，。、；：？！（）《》“”‘’…—·【】":
            return False
        return True
    run = best = 0
    for c in content:
        run = run + 1 if is_bad(c) else 0
        best = max(best, run)

    print(f"[G7] content_chars={n} cjk={cjk} ratio={ratio:.3f} reasoning_tokens={rt} bad_run={best}")
    print(f"[G7] finish={ch.get('finish_reason')} reasoning_len={len(reasoning)}")
    print("[G7] ---- 回答原文 ----")
    print(content[:800])

    # 口径修正：带 PE/RVA/0x1000 等英文术语的正常中文回答 CJK 占比约 0.45，故阈值定为 cjk>=50 且 ratio>=0.35
    ok = (n >= 30) and (cjk >= 50) and (ratio >= 0.35) and (rt == 0) and (best < 3)
    print(f"[G7] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
