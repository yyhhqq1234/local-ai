#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t1_plan_envelope.py -- 计划脚本必须能吃 probe 的信封格式。

缺陷现象
    plan_layers.py 早期只认扁平 {cat: {layer: score}}，而 probe_layers.py 写的是
    {cats: {cat: {probe_by_layer: ...}}, ablation_dloss: {...}} 信封。
    span_of() 收到空 dict → 所有 span 都是 None → 落进 merged-or-unknown 兜底分支。
后果
    不报错，但层段决策完全走兜底：你会以为"探针显示没有明显峰"，其实是格式没读进去。
正确的断言
    norm_by_cat(信封)["kb-re"] 非空，且 span_of(它) 给出 start<=peak<=end 的真区间；
    扁平格式与信封格式得到同一区间。
如果这条 FAIL 说明什么
    plan_layers 又只认一种形状了（或 probe 侧改了信封字段名）——先看 norm_by_cat。
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))          # .../kitty-rev
sys.path.insert(0, os.path.join(KITTY, "scripts"))

import plan_layers as PL  # noqa: E402

curve = {str(l): (0.1 if l < 20 else 0.9 if l < 30 else 0.2) for l in range(16, 40)}
flat = {"kb-re": curve}
envelope = {"cats": {"kb-re": {"probe_by_layer": curve,
                               "probe_by_cat": 0.5, "peak": 25}},
            "ablation_dloss": {"kb-re": curve}}

fails = []
got_flat = PL.norm_by_cat(flat)
got_env = PL.norm_by_cat(envelope)
print(f"[flat ] keys={sorted(got_flat)}")
print(f"[env  ] keys={sorted(got_env)}")

if "kb-re" not in got_env:
    fails.append("信封没解析出 kb-re")
    print("[FAIL] 信封解析为空 —— 这正是当年 span=0 的那条路")
else:
    s_env = PL.span_of(got_env["kb-re"])
    s_flat = PL.span_of(got_flat["kb-re"])
    print(f"[span ] flat={s_flat}  env={s_env}")
    if not s_env:
        fails.append("信封 span_of 为 None")
    elif not (s_env[0] <= s_env[2] <= s_env[1]):
        fails.append(f"信封 span 不满足 start<=peak<=end: {s_env}")
    if s_flat != s_env:
        fails.append(f"两种格式结果不一致 flat={s_flat} env={s_env}")

# 空输入不得崩（也不能伪装成有数据）
if PL.norm_by_cat({"cats": {}}) != {}:
    fails.append("空信封应返回 {}")
if PL.span_of({}) is not None:
    fails.append("空曲线应返回 None")

print("\nPASS: 信封与扁平两种格式都能解析出同一区间" if not fails
      else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
