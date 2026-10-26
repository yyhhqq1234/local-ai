# -*- coding: utf-8 -*-
import json, importlib.util, time, sys
spec = importlib.util.spec_from_file_location("ro", "data/intent3/run_overrefusal.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
rows = {r["id"]: r for r in m.load_rows("data/intent3/overrefusal-40.jsonl")}
for rid in ("or-002","or-007","or-008"):
    r = rows[rid]
    t0=time.time()
    try:
        txt, fld = m.chat("http://127.0.0.1:1234","qwen3.8-27b-ablit-swift15-iq2s",r["prompt"],240,0.0,2048)
        print(f"{rid} OK field={fld} chars={len(txt)} {time.time()-t0:.0f}s  snip={txt[:60]!r}")
    except Exception as e:
        print(f"{rid} FAIL {type(e).__name__}: {e}  {time.time()-t0:.0f}s")
