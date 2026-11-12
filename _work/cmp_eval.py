# -*- coding: utf-8 -*-
"""40 条 RE 评测逐条对照：baseline vs R2(SRA+r3)

用法：python _work/cmp_eval.py <new.json> [<label_in_new>] [<baseline.json>] [<label_in_base>]
默认：new=out/eval-re-sra-r3-v1.json  baseline=out/eval-re-zbv7.json line=zbv4
"""
import io
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
OUT = "train/lines/9b-oxcoder/out"


def load(p):
    return json.load(io.open(p, encoding="utf-8"))


def pick(d, label=None):
    rs = d["results"]
    if label:
        for r in rs:
            if r["label"] == label:
                return r
    return rs[0]


def idx(r):
    return {x["id"]: x for x in r["detail"]}


def main():
    newp = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, "eval-re-sra-r3-v1.json")
    newl = sys.argv[2] if len(sys.argv) > 2 else None
    oldp = sys.argv[3] if len(sys.argv) > 3 else os.path.join(OUT, "eval-re-zbv7.json")
    oldl = sys.argv[4] if len(sys.argv) > 4 else "zbv4"

    n = pick(load(newp), newl)
    o = pick(load(oldp), oldl)
    ni, oi = idx(n), idx(o)

    print("=" * 96)
    print("对照：%s  vs  %s" % (o["label"], n["label"]))
    print("=" * 96)
    fmt = "%-6s %-10s %-4s %-6s %-34s %-6s %-34s"
    print(fmt % ("id", "level", "旧", "旧得", "旧期望", "新", "新得"))
    print("-" * 96)

    flip_bad, flip_good = [], []
    for cid in ni:
        a, b = oi.get(cid), ni[cid]
        if not a:
            continue
        ka = {"hit": "✅", "noarg": "⚠", "wrong": "△", "fake": "❌", "none": "—"}[a["kind"]]
        kb = {"hit": "✅", "noarg": "⚠", "wrong": "△", "fake": "❌", "none": "—"}[b["kind"]]
        mark = " "
        if a["kind"] == "hit" and b["kind"] != "hit":
            mark, _ = "▼", flip_bad.append(cid)
        elif a["kind"] != "hit" and b["kind"] == "hit":
            mark, _ = "▲", flip_good.append(cid)
        print(fmt % (cid, b["level"], ka, ",".join(a["got"]) or "无",
                     ",".join(a["expect"]) or "(负向)",
                     kb + mark, ",".join(b["got"]) or "无"))

    print()
    print("合计  旧 %d/40 (%.1f%%)  新 %d/40 (%.1f%%)  Δ=%+d"
          % (o["hit"], o["acc"] * 100, n["hit"], n["acc"] * 100, n["hit"] - o["hit"]))
    print("分类  旧 hit/noarg/wrong/fake/none = %d/%d/%d/%d/%d"
          % (o.get("hit", 0), o.get("noarg", 0), o.get("wrong", 0), o.get("fake", 0), o.get("none", 0)))
    print("      新 hit/noarg/wrong/fake/none = %d/%d/%d/%d/%d"
          % (n.get("hit", 0), n.get("noarg", 0), n.get("wrong", 0), n.get("fake", 0), n.get("none", 0)))
    for lv in ("L1", "L2", "L3"):
        a = o["by_level"].get(lv, {}); b = n["by_level"].get(lv, {})
        print("      %s  旧 %d/%d  新 %d/%d  Δ=%+d"
              % (lv, a.get("hit", 0), a.get("n", 0), b.get("hit", 0), b.get("n", 0),
                 b.get("hit", 0) - a.get("hit", 0)))
    print()
    print("▼ 退步（旧对→新错）%d 条：%s" % (len(flip_bad), " ".join(flip_bad) or "无"))
    print("▲ 进步（旧错→新对）%d 条：%s" % (len(flip_good), " ".join(flip_good) or "无"))
    print()
    for tag, r in (("旧", o), ("新", n)):
        fk = [x for x in r["detail"] if x["kind"] == "fake"]
        if fk:
            print("%s 编造 %d 条：" % (tag, len(fk)))
            for x in fk:
                print("   [%s/%s] 编造=%s 期望=%s" % (x["id"], x["level"], x["fake"], x["expect"]))
                print("        resp: %s" % x.get("resp", "")[:220].replace("\n", "⏎"))
        else:
            print("%s 编造 0 条" % tag)


main()
