import json, io, sys
sys.stdout.reconfigure(encoding="utf-8")
for f in ["eval-re-zbv4", "eval-re-zbv7", "eval-re-sra-v1"]:
    d = json.load(io.open("train/lines/9b-oxcoder/out/%s.json" % f, encoding="utf-8"))
    print("=" * 70)
    print(f, "| cases_per_adapter =", d["cases_per_adapter"])
    print("  top keys:", list(d.keys()))
    res = d["results"]
    print("  results type:", type(res).__name__, "len:", len(res) if hasattr(res, "__len__") else "-")
    if isinstance(res, list) and res:
        r0 = res[0]
        print("  item0 keys:", list(r0.keys()) if isinstance(r0, dict) else type(r0))
        print("  item0 sample:", json.dumps(r0, ensure_ascii=False)[:600])
