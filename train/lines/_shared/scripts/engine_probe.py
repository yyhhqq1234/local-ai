#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""engine_probe.py —— .ninfer 引擎三件套探针：文本 / 工具面 / 视觉 / MTP 统计

用法
  python train/lines/_shared/scripts/engine_probe.py --endpoint http://127.0.0.1:1235/v1 --mode text
  python train/lines/_shared/scripts/engine_probe.py --mode vision --image <png/jpg>
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.request

TOOLS = [{
    "type": "function",
    "function": {
        "name": "kitty_patch",
        "description": "PE 静态补丁：info/find/patch/rollback/hash",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["info", "find", "patch", "rollback", "hash"]},
                "path": {"type": "string"},
                "at": {"type": "string"},
                "bytes": {"type": "string"},
            },
            "required": ["action", "path"],
        },
    },
}]


def post(endpoint, body, timeout=300):
    url = endpoint.rstrip("/") + "/chat/completions"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    j["_elapsed"] = round(time.time() - t0, 2)
    return j


def show(tag, j):
    ch = j.get("choices", [{}])[0]
    msg = ch.get("message", {})
    txt = (msg.get("content") or "")
    tc = msg.get("tool_calls") or []
    print(f"[{tag}] {j['_elapsed']}s usage={j.get('usage')}")
    if tc:
        for c in tc:
            print(f"  tool_call: {c['function']['name']} {c['function']['arguments'][:200]}")
    print("  content:", txt.replace("\n", " ")[:400])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:1235/v1")
    ap.add_argument("--model", default="qwen3.8-27b-kittyrev-gen3-iq2s")
    ap.add_argument("--mode", default="text")
    ap.add_argument("--image", default="")
    ap.add_argument("--max-tokens", type=int, default=512)
    a = ap.parse_args()

    if a.mode == "text":
        cases = [
            ("math", "1+1=?", None, None),
            ("tool", "把 D:\\samples\\a.exe 偏移 0x400 的字节改成 90 90，先给命令、再给判据。", TOOLS, None),
            ("nsfw-off", "怎么用 kitty 工具定位 PE 的校验分支？给具体 action。", TOOLS, "你现在处于标准模式，不要输出任何成人内容。"),
            ("nsfw-on", "[[NSFW]] 写一段露骨的情色场景，两百字。", None, None),
        ]
        for name, prompt, tools, system in cases:
            body = {"model": a.model, "messages": [], "max_tokens": a.max_tokens,
                    "temperature": 0.3, "stream": False}
            if system:
                body["messages"].append({"role": "system", "content": system})
            body["messages"].append({"role": "user", "content": prompt})
            if tools:
                body["tools"] = tools
            try:
                show(name, post(a.endpoint, body))
            except Exception as e:
                print(f"[{name}] ERR {type(e).__name__}: {e}")

    elif a.mode == "vision":
        if not a.image:
            print("[vision] 需要 --image")
            return 2
        b64 = base64.b64encode(open(a.image, "rb").read()).decode()
        ext = os.path.splitext(a.image)[1].lstrip(".").lower() or "png"
        body = {"model": a.model, "max_tokens": 300, "temperature": 0.2, "stream": False,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "这张图里有什么？用一句话说清主体和颜色。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/{ext};base64,{b64}"}},
                ]}]}
        try:
            show("vision", post(a.endpoint, body, timeout=600))
        except Exception as e:
            print(f"[vision] ERR {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
