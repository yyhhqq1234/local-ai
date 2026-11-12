#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""autodl_market.py —— 查 AutoDL 市场可用 GPU 机器（用 .autodl_token 的 JWT 直接走 v1 API）

用法:
  python autodl_market.py regions
  python autodl_market.py machines [region_sign]
  python autodl_market.py stock            # 汇总各 region 的可用 GPU 型号/价格

输出：原始 JSON 摘要（字段未知时先 dump 键名，便于下一步挑机器/下单）
"""
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, ".autodl_token"), encoding="utf-8").read().strip()
BASE = "https://www.autodl.com/api/v1"


def api(path, body=None, timeout=40):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "authorization": TOKEN,
                                          "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"_http": e.code, "_body": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


def show(label, obj, depth=0, maxitems=4):
    print(f"--- {label} ---")
    s = json.dumps(obj, ensure_ascii=False)
    print(s[:1200])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "regions"
    if cmd == "regions":
        show("machine/region/list", api("/machine/region/list"))
        show("machine/region/list(v2)", api("/machine/region/list", {"page_index": 1, "page_size": 50}))
    elif cmd == "machines":
        region = sys.argv[2] if len(sys.argv) > 2 else ""
        for path in ("/machine/list", "/machine/stock/list"):
            r = api(path, {"region_sign": region, "region": region, "page_index": 1, "page_size": 100})
            show(f"{path} region={region}", r)
    elif cmd == "stock":
        reg = api("/machine/region/list")
        print("regions:", json.dumps(reg, ensure_ascii=False)[:600])
        for path in ("/machine/stock/list", "/machine/list"):
            show(path, api(path, {}))
    else:
        print("用法: regions|machines <region>|stock")


if __name__ == "__main__":
    main()
