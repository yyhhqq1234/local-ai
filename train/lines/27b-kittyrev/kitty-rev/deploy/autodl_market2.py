#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""autodl_market2.py —— 找到可用的机器/库存接口（先用 /region/list，再试多种 body 形态）"""
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, ".autodl_token"), encoding="utf-8").read().strip()
BASE = "https://www.autodl.com/api/v1"


def call(path, body=None, method=None, raw=False):
    method = method or ("POST" if body is not None else "GET")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "authorization": TOKEN,
                                          "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            txt = r.read().decode("utf-8", "replace")
            return r.status, (txt if raw else json.loads(txt))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:200]
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def main():
    code, reg = call("/region/list")
    print("region/list ->", code)
    signs = []
    if isinstance(reg, dict) and reg.get("code") == "Success":
        for r in reg["data"]:
            signs.append(r.get("region_sign"))
            print("   ", r.get("region_sign"), r.get("region_name"), r.get("data_center"), r.get("visible"))
    if not signs:
        return

    s = signs[0]
    bodies = [
        {"region_sign": s, "page_index": 0, "page_size": 10},
        {"region_sign": s, "page_index": 1, "page_size": 10},
        {"region_sign": s, "page_index": 0, "page_size": 10, "task_type": 0},
        {"region_sign": s, "page_index": 0, "page_size": 10, "gpu_type_name": "", "order": "asc"},
        {"region_sign": s},
        {"region": s, "page_index": 0, "page_size": 10},
    ]
    paths = ["/machine/list", "/machine/region/list", "/machine/region/machine/list",
             "/instance/machine/list", "/machine/available/list"]
    for p in paths:
        for b in bodies:
            code, res = call(p, b)
            tag = res if isinstance(res, str) else res.get("code")
            print(f"POST {p:32s} {list(b)[:3]} -> {code} {str(tag)[:80]}")
            if isinstance(res, dict) and res.get("code") == "Success":
                print("   DATA SAMPLE:", json.dumps(res.get("data"), ensure_ascii=False)[:600])
                return
    # GET 形式
    for p in paths:
        code, res = call(f"{p}?region_sign={s}&page_index=0&page_size=10")
        print(f"GET  {p:32s} -> {code} {str(res)[:120]}")


if __name__ == "__main__":
    main()
