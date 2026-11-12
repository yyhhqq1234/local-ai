"""抽查评测明细：看模型实际输出长什么样，验证三段式与背答案判读。"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

d = json.load(open("train/lines/9b-oxcoder/out/eval-heldout.json", encoding="utf-8"))
a = d["adapter"]
print("=" * 88)
print("档3 (re-stage1-r2/final) 逐条明细")
print("=" * 88)
for r in a["detail"]:
    print()
    print("[A %2d] 三段=%d  相似=%.2f  重合=%.2f  命中=%s  编造=%s  GT工具=%s"
          % (r["i"], r["three_part"], r["sim"], r["gram_overlap"],
             ",".join(r["inter"]) or "无", ",".join(r["fake"]) or "无",
             ",".join(r["gt_tools"]) or "无"))
    print("  模型输出: %s" % r["resp_head"][:200])
    print("  参考答案: %s" % r["gt_head"][:200])
