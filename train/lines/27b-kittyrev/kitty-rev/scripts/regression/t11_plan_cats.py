#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t11_plan_cats.py -- 决策树必须说清「看到了哪些类、缺了哪些类」。

缺陷现象（第 12 例，来自反扫 probe_layers 的 L944）
    ① 未知类别：cats_to_mix 用 CAT_TO_DIR.get(cat, "rest") 兜底 → 新类别（如 forge-pe）
       的权重静默并进**回放池**；而 rest 一进 mix，build_mix 就不再追加回放项 →
       回放权重无声变 0。plan 里看不出这一类存在过。
    ② 缺类别：probe 侧某类 <8 条会被 skip，probe_by_cat.json 就那么少一类；
       决策树静默少看它，而兜底分支的 note 写「峰不分离且不在后段」——归因错了
       （你会去调层段，实际该补数据）。
正确的断言
    未知类别 → cats_to_mix 抛 FATAL（不是落 rest）；
    缺类别   → 输出里出现「缺失 [...]」的 warn，且 plan.note 带「本结论不含这几类」；
                report 里 missing_cats 有值。
如果这条 FAIL 说明什么
    未知类别又走 .get(cat,"rest") 兜底了，或 missing/unknown 的报告字段被删。
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# GBK 控制台自保（#32 同族）：本文件会打印 ✓/✗，cp936 下会 UnicodeEncodeError
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
PY = sys.executable
SCRIPT = os.path.join(KITTY, "scripts", "plan_layers.py")

spec = importlib.util.spec_from_file_location("plan_layers_t11", SCRIPT)
PL = importlib.util.module_from_spec(spec)
sys.modules["plan_layers_t11"] = PL
spec.loader.exec_module(PL)

fails = []

# ---------- 1) 未知类别不再落 rest ----------
print("=== 未知类别 ===")
try:
    got = PL.cats_to_mix({"forge-pe": 2})
    fails.append(f"未知类别没报错，得到 {got}")
    print(f"[FAIL] cats_to_mix({{'forge-pe':2}}) = {got}（应当 FATAL）")
except SystemExit as e:
    ok = "未知类别" in str(e)
    print(f"[{'✓' if ok else '✗'}] FATAL: {str(e).splitlines()[0][:96]}")
    if not ok:
        fails.append("FATAL 没点明未知类别")

# 已知类别照旧相加
m = PL.cats_to_mix({"kb-re": 3, "action-reverse": 1})
print(f"[✓] 已知类别相加: {m}")
if m != {"re-train": 4.0}:
    fails.append(f"已知类别相加结果不对: {m}")

# ---------- 2) 缺类别要 warn + note ----------
print("\n=== 缺类别 ===")
tmp = tempfile.mkdtemp(prefix="rg-t11-")
try:
    # 自带最小 fixture：**不许依赖 tmp/fake-probe** —— tmp 会被别的 agent 清掉，
    # 今天已经因此让本测试 FileNotFoundError（与 eval_bare 被删同一起事故）。
    probe = os.path.join(tmp, "probe")
    os.makedirs(probe, exist_ok=True)
    base = os.path.join(KITTY, "tmp", "fake-probe")
    if os.path.isdir(base):
        shutil.copytree(base, probe, dirs_exist_ok=True)
    else:
        cats = ("tool-route", "kb-re", "op-syntax")
        # 信封格式必须是 {"cats": {cat: {"probe_by_layer": {layer: score}}}}
        # （plan_layers.norm_by_cat 读 rec["probe_by_layer"]；写成扁平 {layer: score} 会
        #   让曲线退化成 ablation_dloss 的 float → span_of 崩。实测踩过。）
        env = {"cats": {c: {"probe_by_layer": {str(L): round(1.0 - 0.01 * (L % 7), 4)
                                              for L in range(48, 56)}} for c in cats},
               "ablation_dloss": {c: {str(L): 0.1 for L in range(48, 56)} for c in cats},
               "meta": {"fake": True, "why": "t11 自带 fixture（tmp/fake-probe 被清理）"}}
        with io.open(os.path.join(probe, "probe_by_cat.json"), "w", encoding="utf-8") as f:
            json.dump(env, f, ensure_ascii=False)
    p = os.path.join(probe, "probe_by_cat.json")
    d = json.load(open(p, encoding="utf-8"))
    if "cats" not in d:
        fails.append("fake-probe 的 probe_by_cat.json 不是信封格式，测试前提失效")
    dropped = "tool-route"
    d["cats"].pop(dropped, None)
    if "ablation_dloss" in d:
        d["ablation_dloss"].pop(dropped, None)
    json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)

    out = os.path.join(tmp, "plan.json")
    # 子进程强制 UTF-8：否则 Windows 上子进程按 GBK 输出，父进程按 utf-8 解 → 中文变乱码，
    # 断言 "缺失" 永远不命中（假红，与 run_all 里那条假失败同族）
    r = subprocess.run([PY, SCRIPT, "--probe-dir", probe, "--out", out],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"))
    txt = (r.stdout or "") + (r.stderr or "")
    has_warn = "缺失" in txt and dropped in txt
    print(f"[{'✓' if has_warn else '✗'}] 缺类 warn: "
          f"{next((l for l in txt.splitlines() if '缺失' in l), '(没有)')[:100]}")
    if not has_warn:
        fails.append("缺类别没有 warn")

    if os.path.exists(out):
        rep = json.load(open(out, encoding="utf-8"))
        mc = rep.get("missing_cats")
        note = (rep.get("plan") or {}).get("note", "")
        print(f"[{'✓' if mc else '✗'}] report.missing_cats = {mc}")
        print(f"[note] {note[:110]}")
        if not mc:
            fails.append("report 里没有 missing_cats")
        if "不含它们" not in note:
            fails.append("plan.note 没有追加「本结论不含它们」")
    else:
        fails.append("plan.json 没写出来")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: 未知类别 FATAL、缺类别 warn + note 归因正确"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
