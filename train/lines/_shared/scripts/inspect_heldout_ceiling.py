"""复现 eval_re_heldout.py 的 seed=7 抽样，检查参考答案里到底有没有工具名。

用途：判断「工具命中 5/10」是真漏了 4 条，还是那 4 条的参考答案本身就不含工具名（= 天花板 5/5）。
"""
import io
import json
import random
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

DATA = "train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl"
N = 10
SEED = 7

rows = []
with io.open(DATA, "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i < 20:
            continue
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        msgs = o.get("messages") or []
        sys_m = next((m["content"] for m in msgs if m["role"] == "system"), "")
        usr_m = next((m["content"] for m in msgs if m["role"] == "user"), "")
        asst_m = next((m["content"] for m in msgs if m["role"] == "assistant"), "")
        if sys_m and usr_m and asst_m:
            rows.append((sys_m, usr_m, asst_m))

rng = random.Random(SEED)
picks = rng.sample(rows, min(N, len(rows)))

PAT = re.compile(r"kitty_[a-z0-9_]+")

print("=" * 78)
print("seed=7 抽样的 10 条 held-out —— 参考答案工具名盘点")
print("=" * 78)
n_with_tool = 0
for i, (s, u, a) in enumerate(picks, 1):
    gt = sorted(set(PAT.findall(a)))
    if gt:
        n_with_tool += 1
    print()
    print("[A %2d] 参考答案工具 = %s" % (i, ",".join(gt) if gt else "【无 kitty_ 工具名】"))
    print("      user: %s" % u[:110].replace("\n", "⏎"))
    print("      gt  : %s" % a[:150].replace("\n", "⏎"))

print()
print("=" * 78)
print("结论：10 条里只有 %d 条的参考答案含 kitty_ 工具名" % n_with_tool)
print("      → 工具命中的理论天花板 = %d/%d" % (min(n_with_tool, N), N))
print("      若实测 5/10 == 天花板，则「漏 4 条」的说法不成立，实为满命中")
print("=" * 78)
