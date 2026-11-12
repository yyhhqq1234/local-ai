#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""autodl_market3.py —— 精确试探 /machine/list 的参数组合（找出返回 Success 的那组）"""
import json
import os
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, ".autodl_token"), encoding="utf-8").read().strip()
BASE = "https://www.autodl.com/api/v1"


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "authorization": TOKEN, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:150]}
    except Exception as e:
        return {"_err": f"{type(e).__name__}"}


REGIONS = ["beijing-D", "beijing-E", "west-B", "west-C", "south-A", "east-A"]

VARIANTS = [
    {"region_sign": None, "charge_type": "payg", "only_idle": True, "page_index": 0, "page_size": 10},
    {"region_sign": None, "pay_type": "payg", "only_idle": True, "page_index": 0, "page_size": 10},
    {"region_sign": None, "charge_type": "payg", "only_idle": True, "order_by": "price",
     "page_index": 0, "page_size": 10, "task_type": 0, "gpu_type_name": ""},
    {"region_sign": None, "charge_type": "payg", "page_index": 0, "page_size": 10, "task_type": 0},
    {"region_sign": None, "page_index": 0, "page_size": 10, "charge_type": "payg", "machine_type": "gpu"},
    {"region_sign": None, "page_index": 0, "page_size": 10, "payg": True},
]

for v in VARIANTS:
    for reg in REGIONS[:3]:
        body = dict(v)
        if body.get("region_sign", "x") is None:
            body["region_sign"] = reg
        res = post("/machine/list", body)
        code = res.get("code") if isinstance(res, dict) else res
        print(f"{json.dumps({k: body[k] for k in list(body)[:5]}, ensure_ascii=False)} -> {code}")
        if code == "Success":
            print("DATA:", json.dumps(res.get("data"), ensure_ascii=False)[:800])
            raise SystemExit(0)
