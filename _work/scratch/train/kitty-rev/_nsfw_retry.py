# -*- coding: utf-8 -*-
"""3 条 thinking 超长的题，用 max_tokens 5120 复测"""
import json, urllib.request
w3={json.loads(l)["id"]: json.loads(l) for l in open("data/intent3/w3-bodies.jsonl",encoding="utf-8") if l.strip()}
for rid in ("w3-002","w3-007","w3-010"):
    p=w3[rid]["messages"][0]["content"]
    for mt in (5120,):
        body=json.dumps({"model":"qwen3.8-27b-ablit-swift15-iq2s","max_tokens":mt,"temperature":0.8,
            "messages":[{"role":"user","content":p}]}).encode()
        req=urllib.request.Request("http://127.0.0.1:1234/v1/chat/completions",data=body,
            headers={"Content-Type":"application/json"})
        try:
            d=json.loads(urllib.request.urlopen(req,timeout=600).read())
            ch=d["choices"][0]; m=ch.get("message") or {}
            c=m.get("content") or ""; r=m.get("reasoning_content") or ""
            u=d.get("usage") or {}
            print(f"{rid} mt={mt} content={len(c)} reasoning={len(r)} finish={ch.get('finish_reason')} ctok={u.get('completion_tokens')}", flush=True)
        except Exception as e:
            print(f"{rid} mt={mt} ERR {e}", flush=True)
