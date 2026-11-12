#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_kitty_traj.py — 造「真·工具调用」轨迹数据（修 A1：训练集从未见过 tools schema）

问题（2026-11-01 实测）
  gen3_1p2 54,064 行里 tools 全 null，结构化 tool_calls 只有约 50 行（0.09%）
  → 模型只能学「在正文里手打 <tool_call> 文本」，real-trajectory 能力实测 0/2

做法
  ① 工具 schema 取 kitty-rev/data/intent3/v6-mix/tools.json（60 个真实 schema）
  ② 每一步都是真结构：assistant.tool_calls（name + arguments 按 schema 生成）
     + tool 回包（取 eval_kitty_v6.MOCK 的真实 A 通道回包格式，58 个工具覆盖）
  ③ 每行只挂「本行用到的 2–5 个工具」的最小 schema（ctx 2048，全量 60 个约 3 万 token 会爆）
  ④ 链式模板：侦察→定位→读值→改写 这类真实组合，保证「看回包再决定下一步」

产出
  {cat: tool-route（单步）/ real-trajectory（多步）}，可直接混进训练集

用法
  python build_kitty_traj.py --out data/versions/gen4-traj.jsonl [--target 2000]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import sys
from itertools import cycle

HERE = os.path.dirname(os.path.abspath(__file__))
KREV = os.path.abspath(os.path.join(HERE, "..", "..", "27b-kittyrev", "kitty-rev"))
TOOLS_JSON = os.path.join(KREV, "data", "intent3", "v6-mix", "tools.json")
EVAL_V6 = os.path.join(KREV, "eval", "eval_kitty_v6.py")

SYS = ("你是 kitty 逆向工作台的执行层。每一步都必须发出真正的工具调用（tool_calls），"
       "不要用正文文本模拟调用；拿到回包后按回包内容决定下一步；"
       "全部步骤结束后再用一两句话交代结论。")


def load_tools():
    d = json.load(open(TOOLS_JSON, encoding="utf-8"))
    return {f["function"]["name"]: f for f in d["function_schemas"]}


def load_mock():
    spec = importlib.util.spec_from_file_location("ev6", EVAL_V6)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return dict(m.MOCK)


def enum_of(schema, key):
    p = schema["function"]["parameters"]["properties"].get(key) or {}
    e = p.get("enum")
    return e if e else None


def arg_value(schema, key, rnd, ctx):
    p = schema["function"]["parameters"]["properties"].get(key) or {}
    e = p.get("enum")
    if e:
        return rnd.choice(e)
    t = p.get("type")
    if key == "target":
        return rnd.choice(ctx["targets"])
    if key == "module":
        return rnd.choice(ctx["modules"])
    if key in ("addr", "pa"):
        return "0x%X" % rnd.choice(ctx["addrs"])
    if key in ("size", "len"):
        return rnd.choice([4096, 8192, 1048576, 4096])
    if key in ("samples",):
        return rnd.choice([3, 3, 5])
    if t == "boolean":
        return rnd.choice([True, False])
    if t == "number":
        return rnd.choice([1, 2, 4, 8, 16])
    if key == "op":
        return rnd.choice(ctx["ops"])
    if key == "vt":
        return rnd.choice(["dword", "qword", "byte", "word"])
    if key == "path":
        return rnd.choice(ctx["paths"])
    if key == "name":
        return rnd.choice(ctx["names"])
    if key in ("from", "start", "stop", "to"):
        return "0x%X" % rnd.choice(ctx["addrs"])
    return rnd.choice(ctx["strings"])


def make_args(schema, rnd, ctx, keys=None):
    props = (schema["function"]["parameters"].get("properties") or {})
    if not props:
        return {}
    if keys is None:
        keys = [k for k in props if k in ("action", "op", "target", "module", "addr",
                                         "path", "name", "vt", "size", "samples")]
        if not keys:
            keys = list(props)[:2]
    return {k: arg_value(schema, k, rnd, ctx) for k in keys if k in props}


CTX = {
    "targets": ["kitty-target.exe", "1234", "7788", "game.exe", "kitty-target.exe"],
    "modules": ["kitty-target.exe", "kernel32.dll", "ntdll.dll", "kernelbase.dll"],
    "addrs": [0x7FF75FCD1000, 0x7FF75FCD3000, 0x180001A20, 0x7FF6DADB1000, 0x7FF75FCD2000],
    "ops": ["PING", "LP", "CUR", "MODENUM", "S_GET", "P_WALK", "SYNC_STAT"],
    "paths": ["C:\\samples\\kitty-target.exe", "D:\\samples\\game.exe"],
    "names": ["InitPlugin", "RunTask", "FreeTask", "kernelbase.CreateFileW"],
    "strings": ["kitty-target.exe", "attach", "status"],
}

# 多步链：每步 (工具, 想用到的参数键)。最后一步给结论模板。
CHAINS = [
    ("给当前挂着的目标做一次模块窗口确认：先看桥通不通、有没有开着目标，再列模块。",
     [("kitty_status", ["action"]), ("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "tool-route"),
    ("目标进程还没挂上，先 OPEN 再确认 CUR，然后按模块名取基址。",
     [("kitty_ce", ["op"]), ("kitty_ce", ["op"]), ("kitty_sym", ["action", "module"])], "tool-route"),
    ("在模块窗口里按 dword 精确扫一个值，拿到命中后读回验证。",
     [("kitty_ce", ["op"]), ("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "real-trajectory"),
    ("扫描后命中好几条，逐条读值确认哪一条是真的血量。",
     [("kitty_ce", ["op"]), ("kitty_ce", ["op"]), ("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "real-trajectory"),
    ("已知血量地址，反查谁指向它，再把跳数拉长验证稳定性。",
     [("kitty_pchain", ["target"]), ("kitty_ce", ["op"]), ("kitty_pchain", ["target"])], "real-trajectory"),
    ("对目标做反作弊三视图门禁：先起引擎桥，再跑 acescan，最后看双视图结果。",
     [("kitty_drv", ["action"]), ("kitty_acescan", ["target", "module"]), ("kitty_dualview", ["addr"])], "real-trajectory"),
    ("下断点抓一次调用：attach、下 execute 断点、继续、读寄存器。",
     [("kitty_dbg", ["action"]), ("kitty_dbg", ["action", "addr"]), ("kitty_dbg", ["action"]), ("kitty_dbg", ["action"])], "real-trajectory"),
    ("静态查一下 PE 的导出和导入，给后续定位做准备。",
     [("kitty_sym", ["action", "path"]), ("kitty_sym", ["action", "path"])], "tool-route"),
    ("把目标模块 dump 下来并重建镜像，用于离线分析。",
     [("kitty_dump", ["module"]), ("kitty_dump", ["module"])], "real-trajectory"),
    ("接管宿主要先确保驱动在：先 ensure 再看 status。",
     [("kitty_drv", ["action"]), ("kitty_drv", ["action"])], "tool-route"),
    ("做一次内存写回环验证：读、写同值、再读确认没变。",
     [("kitty_ce", ["op"]), ("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "real-trajectory"),
    ("用 Lua 逃生口做一次只读探针，确认地址可读再决定下一步。",
     [("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "real-trajectory"),
    ("核对引擎参数是否生效：看 engine 状态，再看桥状态。",
     [("kitty_init", ["action"]), ("kitty_status", ["action"])], "tool-route"),
    ("对 APK 先做一次反编译，再看 shell 指纹。",
     [("kitty_jadx", ["target"]), ("kitty_apkscan", ["action", "target"])], "tool-route"),
    ("Unity 目标：先看加载器状态，再做 IL2CPP dump。",
     [("kitty_bepinex", ["action"]), ("kitty_il2cppdumper", ["action"])], "tool-route"),
    ("UE 目标：先看 UE4SS 状态，再 dump SDK。",
     [("kitty_ue4ss", ["action"]), ("kitty_uedump", ["action"])], "tool-route"),
    ("排查一次操作失败：先看桥，再看引擎，再定位到具体 OP。",
     [("kitty_status", ["action"]), ("kitty_init", ["action"]), ("kitty_ce", ["op"])], "real-trajectory"),
    ("把一段校验改成直接放行，先定位字节再补丁并校验。",
     [("kitty_patch", ["action", "path"]), ("kitty_patch", ["action", "path"]), ("kitty_patch", ["action", "path"])], "real-trajectory"),
    ("给工具面做一次体检：看健康、看变体、看软件面。",
     [("kitty_status", ["action"]), ("kitty_variants", ["action"]), ("kitty_drvio", ["action"])], "tool-route"),
    ("目标进程里搜一段特征码，确认命中后再读上下文。",
     [("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "real-trajectory"),
    # 错误恢复链：第一次故意踩坑（回 ERR），第二次按错误码修正
    ("按值扫描报 need-range，补上显式区间再扫一次。",
     [("kitty_ce", ["op"], "err"), ("kitty_ce", ["op"])], "error-recovery"),
    ("反查指针报窗口过大，缩到模块窗口内重试。",
     [("kitty_pchain", ["target"], "err"), ("kitty_pchain", ["target"])], "error-recovery"),
    ("下断点被闸门拒了，先看状态再决定是否 attach。",
     [("kitty_dbg", ["action"], "err"), ("kitty_dbg", ["action"])], "error-recovery"),
    ("写内存报保护失败，先探可写性再写回。",
     [("kitty_ce", ["op"], "err"), ("kitty_ce", ["op"]), ("kitty_ce", ["op"])], "error-recovery"),
]

INTENT_TPL = (
    "先确认{}.", "这一步用{}。", "调{}看一下。", "先用{}拿基础信息。",
    "接下来{}。", "换{}继续。", "{}走一次。", "用{}核对一遍。",
)

ERR = {
    "kitty_ce": "ERR|need-range",
    "kitty_pchain": "ERR|window-too-wide|max-window=16MB",
    "kitty_dbg": "ERR|gate|accept_host_loss required",
    "kitty_patch": "ERR|expect-mismatch",
    "kitty_prot": "ERR|protect-fail|0x5",
}

CONCLUSION = {
    "tool-route": "按回包顺序走完，结论：{c}",
    "real-trajectory": "{c}——这条路径通了，下一步沿用同一窗口继续。",
    "error-recovery": "{c}改完重试即通过。",
}


def build_row(rnd, tools, mock, chain, cat, idx):
    task, steps, _ = chain
    msgs = [{"role": "system", "content": SYS}, {"role": "user", "content": task}]
    used = []
    notes = []
    for si, step in enumerate(steps):
        tool, keys = step[0], step[1]
        mode = step[2] if len(step) > 2 else "ok"
        schema = tools.get(tool)
        if not schema:
            return None
        call_id = "call_%d_%d" % (idx, si)
        args = make_args(schema, rnd, CTX, keys)
        # 关键：content 不能为空，否则训练出「空回答」先验（gen4 塌陷主因，5,390/27,806=19.4%）
        _intent = rnd.choice(INTENT_TPL).format(tool)
        msgs.append({"role": "assistant", "content": _intent,
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": tool, "arguments": args}}]})
        if mode == "err":
            reply = ERR.get(tool, "ERR|need-range")
        else:
            # 变动尾巴：同一工具每次回包不完全一致，避免模型把回包当固定串背下来
            reply = "%s|t=%d|seq=%d" % (mock.get(tool, "OK"), rnd.randint(100, 999), si + 1)
        msgs.append({"role": "tool", "tool_call_id": call_id, "content": reply})
        used.append(tool)
        notes.append(reply[:60])
    # C19 教训：别把回包原文整段塞进结论，否则 8-gram 重复率飙到 0.4
    _open = ("已确认", "先给结论：", "按回包，", "结论是", "结果是")
    _tail = ("可以继续。", "下一步照此推进。", "按这个走。", "以此为准。", "后续沿用。")
    _c = (rnd.choice(_open) + notes[-1][:18].strip() + "，" + rnd.choice(_tail)) if notes else "已完成。"
    msgs.append({"role": "assistant", "content": _c})
    uniq = []
    for u in used:
        if u not in uniq:
            uniq.append(u)
    return {"messages": msgs,
            "tools": [tools[u] for u in uniq],
            "meta": {"cat": cat}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", type=int, default=1800, help="目标行数")
    ap.add_argument("--singles", type=int, default=8, help="每个工具的覆盖条数")
    ap.add_argument("--seed", type=int, default=20261102)
    a = ap.parse_args()

    tools = load_tools()
    mock = load_mock()
    rnd = random.Random(a.seed)

    rows, seen = [], set()
    i = 0
    seq = cycle(CHAINS)
    while len(rows) < a.target:
        i += 1
        task, steps, cat = next(seq)
        r = build_row(rnd, tools, mock, (task, steps, cat), cat, i)
        if not r:
            continue
        key = hashlib.blake2b(
            json.dumps([m.get("tool_calls") for m in r["messages"]], sort_keys=True,
                       ensure_ascii=False).encode(), digest_size=8).hexdigest()
        if key in seen:
            if i > a.target * 40:
                break
            continue
        seen.add(key)
        rows.append(r)
        if i > a.target * 40:
            break

    # ── 单工具覆盖：保证 60 个工具每个都出现过（链模板只覆盖了一部分）──
    covered = {t["function"]["name"] for r in rows for t in r["tools"]}
    per = max(6, a.singles)
    j = 0
    for name in sorted(tools):
        schema = tools[name]
        desc = schema["function"].get("description", "")[:40]
        action = (schema["function"]["parameters"]["properties"].get("action") or {})
        act = (action.get("enum") or [""])[0]
        for v in range(per):
            j += 1
            args = make_args(schema, rnd, CTX, None)
            call_id = "call_s%d" % j
            reply = mock.get(name, "OK")
            task = ("用 %s 处理一次：%s" % (name, desc)) if not act else \
                   ("用 %s 的 %s 动作处理一次：%s" % (name, act, desc))
            msgs = [
                {"role": "system", "content": SYS},
                {"role": "user", "content": task},
                {"role": "assistant", "content": rnd.choice(INTENT_TPL).format(name),
                 "tool_calls": [{"id": call_id, "type": "function",
                                 "function": {"name": name, "arguments": args}}]},
                {"role": "tool", "tool_call_id": call_id, "content": reply},
                {"role": "assistant", "content": "回包：%s。按这个结果可以继续下一步。"
                                                % reply[:80]},
            ]
            rows.append({"messages": msgs, "tools": [schema],
                         "meta": {"cat": "tool-route"}})
            covered.add(name)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(a.out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    sha = h.hexdigest()
    open(a.out + ".sha256", "w", encoding="utf-8", newline="\n").write(sha + "\n")

    n_calls = sum(sum(len(m.get("tool_calls") or []) for m in r["messages"]) for r in rows)
    cats = {}
    for r in rows:
        cats[r["meta"]["cat"]] = cats.get(r["meta"]["cat"], 0) + 1
    print(f"[out] {a.out}  {len(rows)} 行  "
          f"{os.path.getsize(a.out)/(1<<20):.1f} MiB  sha {sha[:16]}")
    print(f"[stat] tool_calls 总数 {n_calls}（均值 {n_calls/max(1,len(rows)):.2f}/行）  cats={cats}")
    print(f"[stat] 工具覆盖 {len({u for r in rows for u in [t['function']['name'] for t in r['tools']]})}/60")
    return 0


if __name__ == "__main__":
    sys.exit(main())
