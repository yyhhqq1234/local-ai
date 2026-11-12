#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""autodl_scan.py —— 扫全 region 的空闲 GPU 机器（≥24GB 显存），输出可租清单

判据：gpu_idle_num > 0 且 gpu_memory >= 24e9（要跑 27B QLoRA + 51G bf16 合并/量化）
用法：python autodl_scan.py [min_gb]
"""
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = open(os.path.join(HERE, ".autodl_token"), encoding="utf-8").read().strip()
BASE = "https://www.autodl.com/api/v1"
MIN_GB = float(sys.argv[1]) if len(sys.argv) > 1 else 24.0


def get(path):
    req = urllib.request.Request(BASE + path, method="GET",
                                 headers={"authorization": TOKEN, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "authorization": TOKEN, "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}


def main():
    reg = get("/region/list")
    if reg.get("code") != "Success":
        print("region/list failed:", reg)
        return
    rows = []
    for r in reg["data"]:
        sign = r.get("region_sign")
        res = post("/machine/list", {"region_sign": sign, "charge_type": "payg",
                                     "only_idle": True, "page_index": 0, "page_size": 100})
        if res.get("code") != "Success":
            print(f"[skip] {sign}: {res.get('code')}")
            continue
        lst = (res.get("data") or {}).get("list") or []
        for m in lst:
            mem_gb = (m.get("gpu_memory") or 0) / 1e9
            idle = m.get("gpu_idle_num") or 0
            if idle <= 0 or mem_gb < MIN_GB:
                continue
            price = (m.get("payg_price") or m.get("price") or m.get("unit_price")
                     or m.get("price_per_hour") or "")
            rows.append({
                "region": sign, "region_name": m.get("region_name"),
                "machine_id": m.get("machine_id"), "machine": m.get("machine_alias"),
                "gpu": m.get("gpu_name"), "mem_gb": round(mem_gb, 1), "idle": idle,
                "gpu_num": m.get("gpu_number"), "price": price,
                "disk_gb": round((m.get("max_instance_disk_size") or 0) / 1e9),
                "cuda": m.get("highest_cuda_version"),
            })
    rows.sort(key=lambda x: (-x["mem_gb"], x["region"]))
    print(f"=== idle GPU machines with >= {MIN_GB} GB : {len(rows)} ===")
    for r in rows:
        print(f'{r["region"]:10s} {str(r["region_name"]):8s} {r["machine_id"]} {str(r["machine"]):14s} '
              f'{str(r["gpu"]):16s} {r["mem_gb"]:5.1f}GB x{r["gpu_num"]} idle={r["idle"]} '
              f'disk={r["disk_gb"]}GB cuda={r["cuda"]} price={r["price"]}')
    if rows:
        keys = sorted({k for r in rows for k in r})
        print("\nraw sample:", json.dumps(rows[0], ensure_ascii=False))


if __name__ == "__main__":
    main()
