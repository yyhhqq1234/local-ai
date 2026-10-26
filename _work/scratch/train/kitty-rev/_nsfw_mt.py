# -*- coding: utf-8 -*-
"""NSFW 交付可用性：content 为空是否是 max_tokens 不足导致（只统计，不打印内容）"""
import json, urllib.request
w3 = {json.loads(l)["id"]: json.loads(l) for l in open("data/intent3/w3-bodies.jsonl", encoding="utf-8") if l.strip()}
probe = ["w3-001","w3-003","w3-005","w3-004","w3-007"]
for mt in (1024, 2048, 3072):
    print(f"\n===== max_tokens={mt} =====")
    for rid in probe:
        p = w3[rid]["messages"][0]["content"]
        body = json.dumps({"model":"qwen3.8-27b-ablit-swift15-iq2s","max_tokens":mt,
            "temperature":0.8,"messages":[{"role":"user","content":p}]}).encode()
        req = urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",
            data=body, headers={"Content-Type":"application/json"})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=300).read())
            ch = d["choices"][0]; msg = ch.get("message") or {}
            c = msg.get("content") or ""
            r = msg.get("reasoning_content") or ""
            u = d.get("usage") or {}
            print(f"  {rid:<8} content={len(c):<5} reasoning={len(r):<5} finish={ch.get('finish_reason'):<10} "
                  f"completion_tokens={u.get('completion_tokens')}")
        except Exception as e:
            print(f"  {rid:<8} ERR {e}")
