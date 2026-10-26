# -*- coding: utf-8 -*-
"""探测 AutoDL 登录 API 端点（凭据经环境变量传入，不落盘）"""
import json, os, urllib.request, urllib.error
PHONE = os.environ["ADL_PHONE"]; PW = os.environ["ADL_PW"]
cands = [
    ("https://www.autodl.com/api/v1/user/login", {"phone": PHONE, "password": PW}),
    ("https://www.autodl.com/api/v1/user/login", {"username": PHONE, "password": PW}),
    ("https://api.autodl.com/api/v1/user/login", {"phone": PHONE, "password": PW}),
]
for url, body in cands:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", "replace")
            print(f"[{r.status}] {url}  body={list(body)}")
            print("   ", raw[:400])
    except urllib.error.HTTPError as e:
        print(f"[{e.code}] {url}  body={list(body)}  {e.read()[:200]}")
    except Exception as e:
        print(f"[ERR] {url}  {type(e).__name__}: {e}")
