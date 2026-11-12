#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""autodl_probe.py —— 探测 AutoDL v1 API 里"可用机器/市场"路由（GET+POST 双试，只报状态码）"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, ".autodl_token"), encoding="utf-8").read().strip()
BASE = "https://www.autodl.com/api/v1"

CANDS = [
    "/machine/region/list", "/machine/list", "/machine/stock", "/machine/stock/list",
    "/region/list", "/instance/gpu_stock", "/instance/stock", "/gpu/stock",
    "/machine/region/stock", "/market/list", "/machine/market/list",
    "/instance/list", "/instance/status", "/user/instance/list",
]

BODY = {"region_sign": "", "page_index": 1, "page_size": 50, "task_type": 0}


def call(path, method):
    data = json.dumps(BODY).encode() if method == "POST" else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "authorization": TOKEN,
                                          "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, body[:160]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:120]
    except Exception as e:
        return -1, f"{type(e).__name__}"


def main():
    for path in CANDS:
        for method in ("POST", "GET"):
            code, body = call(path, method)
            print(f"{method:4s} {path:32s} -> {code}  {body[:110]}")
            if code == 200:
                break


if __name__ == "__main__":
    main()
