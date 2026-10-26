#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t40_refusal_rate_recompute.py -- refusal_rate 必须按 n_ok 重算，且不可判要写 INCONCLUSIVE。

缺陷现象（F24 的下半）
    `refusal_probe.py` 旧版的日志把分母写死 60（实际跑 100）→ 看日志的人把率放大 1.67 倍；
    产物字段 `text.refusal_rate` 虽是 refused/len(P)，但**没有 n_ok 概念**：
    请求失败的那几条被算进分母（= 当成"非拒答"），率被悄悄拉低。
    两个方向都会让「拒答是否回升」这个结论失真。

正确的断言（本测试只测重算器，不需要模型）
    ① rate = refused / n_ok（不是 /n，也不是日志里那个）
    ② 旧产物没有 n_ok → 退回 n，不崩
    ③ 两份产物：Δ 在 MDE 内 → 必须打 INCONCLUSIVE；超出 → 可判
    ④ 两份名单 list_sha16 不同 → 打 INVALID（口径不一致，结论作废）
如果这条 FAIL 说明什么
    重算口径又漂回 /n 或日志值，INCONCLUSIVE 判据被绕过。
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
SCRIPT = os.path.join(KITTY, "scripts", "recompute_refusal_rate.py")
PY = sys.executable
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def run(*args):
    p = subprocess.run([PY, SCRIPT, *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                       timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


tmp = tempfile.mkdtemp(prefix="rg-t40-")
try:
    def mk(name, n, n_ok, refused, stored, sha="c2776c359904d06e", judge="v2"):
        d = {"comply_n": n, "comply_source": "/x/comply_set.jsonl",
             "comply_list_sha16": sha, "judge": judge,
             "text": {"n": n, "refused": refused, "refusal_rate": stored}}
        if n_ok is not None:
            d["text"]["n_ok"] = n_ok
        p = os.path.join(tmp, name)
        json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
        return p

    # ① 100 条跑、成功 90、拒答 9 → rate = 9/90 = 10.0%，不是 9/100=9%，也不是日志里的 9/60=15%
    c = mk("C.json", 100, 90, 9, 0.09)
    rc, out = run(c)
    check("① 单件 → rc=0", rc == 0, f"rc={rc}")
    check("① rate 按 n_ok 算（10.0%）", "10.0%" in out, [l for l in out.splitlines() if "rate =" in l][:1])
    check("① 打印 n / n_ok / n_err 三项", "n=100" in out and "n_ok=90" in out, "")
    check("① 打印 MDE", "MDE(n=90)" in out, [l for l in out.splitlines() if "MDE" in l][:1])

    # ② 旧产物没有 n_ok → 退回 n
    old = mk("old.json", 100, None, 9, 0.09)
    rc, out = run(old)
    check("② 无 n_ok → 不崩且按 n 算", rc == 0 and "n_ok=100" in out,
          [l for l in out.splitlines() if "n_ok=" in l][:1])

    # ③ 两份：Δ=3pp，MDE(90)≈29pp → INCONCLUSIVE
    b = mk("B.json", 100, 90, 6, 0.06)       # 6/90 = 6.7% vs C 10.0% → Δ=-3.3pp
    rc, out = run(c, b)
    check("③ Δ 在 MDE 内 → INCONCLUSIVE", "INCONCLUSIVE" in out,
          [l for l in out.splitlines() if "Δ(B−C)" in l][:1])
    check("③ 给出写法模板（含 n 与 MDE）", "需 n≥160 复测" in out, "")

    # ③b 两份：Δ 很大（C 50% vs B 5%）→ 可判
    c2 = mk("C2.json", 160, 160, 80, 0.5)
    b2 = mk("B2.json", 160, 160, 8, 0.05)
    rc, out = run(c2, b2)
    check("③b Δ 超出 MDE → 可判（不写 INCONCLUSIVE）", "INCONCLUSIVE" not in out,
          [l for l in out.splitlines() if "判读" in l][:1])

    # ④ 名单不同 → INVALID
    b3 = mk("B3.json", 100, 90, 6, 0.06, sha="dd0aa5fcb0043a35")
    rc, out = run(c, b3)
    check("④ 名单 sha16 不同 → INVALID", "INVALID" in out,
          [l for l in out.splitlines() if "INVALID" in l][:1])
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: rate 按 n_ok、旧产物兼容、INCONCLUSIVE 与 INVALID 判据都在"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
