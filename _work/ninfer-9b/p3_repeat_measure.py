# p3_repeat_measure.py — 同一 artifact 重复测 3 次，验证 acceptance 是否稳定（判据可复现性）
import importlib.util
import json
import os
import sys

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
spec = importlib.util.spec_from_file_location("ns", os.path.join(BASE, "p3_norm_sweep.py"))
ns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ns)

ARTS = [
    ("mtp2f(00:33 头)", "kittyrev-oxcoder9b-mtp2f-GSQ.ninfer"),
    ("S-all(01:23 头)", "kittyrev-oxcoder9b-S-all.ninfer"),
]
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

for label, name in ARTS:
    path = os.path.join(ns.OUTDIR, name)
    if not os.path.exists(path):
        print(label, "MISSING"); continue
    rows = [ns.measure(path) for _ in range(3)]
    rates = [r.get("rate") for r in rows]
    print("%-16s %s  decode=%s" % (label, json.dumps(rows, ensure_ascii=False),
                                   [r.get("decode_tok_s") for r in rows]))
    print("   rates:", rates)
