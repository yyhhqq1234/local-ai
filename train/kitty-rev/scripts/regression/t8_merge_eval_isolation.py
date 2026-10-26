#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t8_merge_eval_isolation.py -- 隔离基线缺失必须拒跑，清单必须跟着 --out 走。

缺陷现象（回归扫描扫出来的第 8、9 例）
    ① ev = jlines(args.eval) if os.path.exists(args.eval) else []
       → --eval 路径打错 → ev=[] → ev_f/ev_u 为空 → 「与 eval 冲突就 ABORT」永不触发，
         而 manifest 还记 eval_rows=0 / collisions=0，看起来"干净"。
    ② merge-manifest.json 写死 os.path.join(OUTDIR, ...)
       → --out 指到别处时，数据写在 A、清单写在 B（甚至覆盖 B 里那次真跑的清单）。
后果
    ① 新数据可能把 eval 集的内容并进训练集，隔离检查形同不存在。
    ② 拿 B 的清单去核对 A 的内容，字段全对不上；或者真跑的那份清单被静默覆盖。
正确的断言
    --eval 不存在 / 为空 → 非零退出 + REFUSE；
    自定义 --out → merge-manifest.json 与数据同目录。
如果这条 FAIL 说明什么
    又有人把"缺失"当成"空"处理（.get/if exists else [] 家族），或清单路径又回到常量。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
SCRIPT = os.path.join(KITTY, "scripts", "merge_forge.py")

fails = []
tmp = tempfile.mkdtemp(prefix="rg-t8-")
try:
    # 最小输入：一个 source jsonl + 一个 eval jsonl
    src = os.path.join(tmp, "src.jsonl")
    ev = os.path.join(tmp, "eval.jsonl")
    row = {"messages": [{"role": "user", "content": "q1"},
                        {"role": "assistant", "content": "a1"}]}
    for p in (src, ev):
        with open(p, "w", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    out = os.path.join(tmp, "deep", "out.jsonl")     # 目录不存在
    p = subprocess.run([PY, SCRIPT, "--src", src, "--out", out, "--eval",
                        os.path.join(tmp, "missing-eval.jsonl")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    txt = p.stdout + p.stderr
    print(f"[eval缺失] rc={p.returncode}  {txt.strip().splitlines()[-1] if txt.strip() else ''}")
    if p.returncode == 0 or "REFUSE" not in txt:
        fails.append("--eval 缺失没有拒跑")

    p = subprocess.run([PY, SCRIPT, "--src", src, "--out", out, "--eval", ev],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(f"[正常跑  ] rc={p.returncode}")
    if p.returncode != 0:
        fails.append(f"正常跑失败: {(p.stdout + p.stderr).strip()[-160:]}")
    mp = os.path.join(os.path.dirname(out), "merge-manifest.json")
    if not os.path.exists(mp):
        fails.append(f"清单没写到 {mp}（说明还写死在 OUTDIR）")
    else:
        m = json.load(open(mp, encoding="utf-8"))
        print(f"[清单    ] {os.path.relpath(mp, tmp)}  rows_total={m.get('rows_total')} "
              f"eval_rows={m.get('eval_isolation', {}).get('eval_rows')}")
        if m.get("eval_isolation", {}).get("eval_rows") != 1:
            fails.append("清单里的 eval_rows 不对（隔离基线没被记录）")
        if os.path.abspath(m.get("out", "")) and \
                os.path.basename(m["out"]) != "out.jsonl":
            fails.append(f"清单里的 out 字段不对: {m.get('out')}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 隔离基线缺失被拒、清单与数据同目录" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
