# -*- coding: utf-8 -*-
import json, glob, os
cands = glob.glob(r"D:\BaiduNetdiskDownload\Local-AI\ninfer-27b-kv-stream-3arch-20261019\model\*.conversion.json")
cands += glob.glob(r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\local-pack\*.conversion.json")
for p in cands:
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("SKIP", os.path.basename(p), e); continue
    f = {k: v for k, v in (d.get("formats") or {}).items() if "iq" in k or "q4_k" in k or "q5_k" in k or "q8_0" in k}
    comps = sorted((d.get("components") or {}).keys())
    print("=" * 78)
    print("FILE   ", os.path.basename(p))
    print("PAYLOAD", d.get("payload_bytes"))
    print("COMPS  ", comps)
    print("QUANT  ", json.dumps(f, ensure_ascii=False))
    print("SRC    ", json.dumps((d.get("provenance") or {}).get("sources"), ensure_ascii=False)[:220])
