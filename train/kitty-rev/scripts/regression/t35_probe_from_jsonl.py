#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t35_probe_from_jsonl.py -- refusal 探针的样本量必须可扩到 160，且缺参不许退回 60。

缺陷现象
    refusal_probe.py 的配合集是**代码内联的 60 条 COMPLY**。
    n=60 时 refusal_rate 的 95% 置信区间 ≈ ±12pp，最小可检出差异(MDE) ≈ 25.6pp；
    而验收阈值是「上升 ≤10pp」/「下降 ≥20pp」——
      · 10pp 判据：MDE 25.6 > 10 → **恒过**（永远判"没变差"）
      · 20pp 判据：漏判率 ≈40%
    即"拒答判据"在 60 条上是装饰品，而报告里它看起来有数、有百分比。
后果
    v4 的 abliteration 是否被 SFT 削弱，用 60 条根本测不出来；结论却是"通过"。
正确的断言
    ① 默认行为不变（不给 --from-jsonl → 仍是内联 60 条，dry-run 报 60 / builtin 来源）
    ② --from-jsonl 路径打错 → rc=2（**不许**退回 60 条：那会把样本量不足伪装成通过）
    ③ 源文件 0 条可用 → rc=2
    ④ --limit > 池子 → rc=2（静默取少 = 分母对不上）
    ⑤ 正常 --limit 160 → rc=0，且两次抽样 sha16 相同（可复现），emit-list 行数=160
如果这条 FAIL 说明什么
    样本量扩展被删，或缺参又退回内联 60 条（判据重新变成恒过）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(KITTY, "scripts", "refusal_probe.py")
COMPLY = os.path.join(KITTY, "data", "reablit", "comply_set.jsonl")
PY = sys.executable
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def run(*args):
    p = subprocess.run([PY, SCRIPT, "--dry-run", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                       timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


# ① 默认行为不变
rc, out = run()
check("① 默认 → rc=0 且 60 条内联", rc == 0 and "COMPLY=60" in out, f"rc={rc}")
check("① 默认来源标明 builtin", "builtin:COMPLY" in out,
      [l for l in out.splitlines() if "来源" in l][:1])

# ② 路径打错 → rc=2
rc, out = run("--from-jsonl", os.path.join(HERE, "no_such_file.jsonl"), "--limit", "160")
check("② 路径错 → rc=2", rc == 2, f"rc={rc}")
check("② 报错点明不许退回 60 条", "退回内联 60 条" in out,
      [l for l in out.splitlines() if "FATAL" in l][:1])

tmp = tempfile.mkdtemp(prefix="rg-t35-")
try:
    # ③ 0 条可用
    empty = os.path.join(tmp, "empty.jsonl")
    open(empty, "w", encoding="utf-8").close()
    rc, out = run("--from-jsonl", empty, "--limit", "160")
    check("③ 空文件 → rc=2", rc == 2, f"rc={rc}")
    check("③ 报错说 0 条可用", "0 条可用" in out,
          [l for l in out.splitlines() if "FATAL" in l][:1])

    # ④ limit > pool
    small = os.path.join(tmp, "small.jsonl")
    with open(small, "w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"prompt": f"q{i}"}, ensure_ascii=False) + "\n")
    rc, out = run("--from-jsonl", small, "--limit", "160")
    check("④ pool<limit → rc=2", rc == 2, f"rc={rc}")
    check("④ 报错点明分母问题", "分母" in out or "可用条数" in out,
          [l for l in out.splitlines() if "FATAL" in l][:1])

    # ⑤ 正常 160（真数据）
    if not os.path.isfile(COMPLY):
        check("⑤ 缺 comply_set.jsonl", False, COMPLY)
    else:
        lst = os.path.join(tmp, "list.jsonl")
        rc1, out1 = run("--from-jsonl", COMPLY, "--limit", "160", "--emit-list", lst)
        check("⑤ 160 条 → rc=0", rc1 == 0, f"rc={rc1}")
        check("⑤ dry-run 报 160 / pool=320", "COMPLY=160" in out1 and "pool=320" in out1,
              [l for l in out1.splitlines() if "COMPLY=" in l][:1])
        sha1 = [l for l in out1.splitlines() if "名单 sha16" in l]
        check("⑤ 打印名单 sha16", bool(sha1), sha1[:1])
        n = sum(1 for _ in open(lst, encoding="utf-8"))
        check("⑤ emit-list 行数 = 160", n == 160, str(n))
        rc2_, out2 = run("--from-jsonl", COMPLY, "--limit", "160")
        sha2 = [l for l in out2.splitlines() if "名单 sha16" in l]
        check("⑤ 两次抽样 sha16 相同（可复现）", sha1 and sha1 == sha2, f"{sha1[:1]} vs {sha2[:1]}")
        # 抽样确实打散：名单前 5 条不等于源文件前 5 条
        src_head = [json.loads(l)["prompt"] for l in open(COMPLY, encoding="utf-8").readlines()[:5]]
        got_head = [json.loads(l)["prompt"] for l in open(lst, encoding="utf-8").readlines()[:5]]
        check("⑤ 抽样不是取文件前 160 行（按 sha16 排序）", src_head != got_head,
              f"src[0]={src_head[0][:20]!r} got[0]={got_head[0][:20]!r}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 默认 60 条不变、缺参 FATAL、160 条可复现且名单可复核"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
