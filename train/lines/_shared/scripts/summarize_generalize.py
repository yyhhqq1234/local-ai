"""四档泛化测试结果汇总表。"""
import glob
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

files = [f for f in sorted(glob.glob("train/lines/9b-oxcoder/out/eval-gen-*.json")) if "probe" not in f]
print("=" * 76)
print("RE 真泛化测试 —— 四档汇总（12 条改写提问 · 去工具名提示）")
print("=" * 76)
hdr = "标签", "命中率", "选错", "编造", "回避", "L1", "L2", "L3"
print("%-12s %-9s %-6s %-6s %-6s %-7s %-7s %-7s" % hdr)

for f in files:
    d = json.load(open(f, encoding="utf-8"))
    lv = d["by_level"]
    def lvs(k):
        x = lv.get(k, {})
        return "%d/%d" % (x.get("hit", 0), x.get("n", 4))
    print("%-12s %-9s %-6d %-6d %-6d %-7s %-7s %-7s" % (
        d["tag"], "%.1f%%" % (d["acc"] * 100),
        d["wrong"], d["fake"], d["none"],
        lvs("L1"), lvs("L2"), lvs("L3"),
    ))

print()
print("=" * 76)
print("逐条对位（档2 vs 档3）")
print("=" * 76)
dd = {}
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    dd[d["tag"]] = {x["id"]: x for x in d["detail"]}

tags = list(dd.keys())
for cid in ["G%02d" % i for i in range(1, 13)]:
    row = []
    for t in tags:
        x = dd[t].get(cid, {})
        row.append("%s:%s" % (t, x.get("kind", "?")))
    print("  %s  " % cid + "  ".join(row))
