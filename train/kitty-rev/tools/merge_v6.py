#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_v6.py — 合成最终 V6 训练集

三块拼：
  A 工具子集     v6-mix/train.jsonl（615 条，多步轨迹 + 直调，带 tools schema）
  B kitty_ops 合法用法  10 条（避免把合法工具彻底删掉的副作用）
  C 文本子集     v5-mix 精选（NSFW 150 全保留 + 通用问答，不带 tools）

输出 data/intent3/v6-mix/train.final.jsonl
"""
import json
import os
import random
import re
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
D = os.path.join(ROOT, "data", "intent3")
OUT = os.path.join(D, "v6-mix", "train.final.jsonl")

W3 = os.path.join(D, "w3-bodies.jsonl")
V5 = os.path.join(D, "v5-mix", "train.jsonl")
V6 = os.path.join(D, "v6-mix", "train.jsonl")
TOOLS = os.path.join(D, "v6-mix", "tools.json")

SYS = ("你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。"
       "工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，"
       "按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。")

# ── B: kitty_ops 的合法用法（查冻结表本身是合理任务，只是不该做默认第一步）
OPS_LEGIT = [
    ("A 通道现在有哪些 OP 可以用？", {"filter": "*"},
     "OK|66 ops|PING VER LP OPEN CUR R W ALLOC MODENUM MODBASE DIS S_NEW S_GET P_BACK KM_R KM_W…",
     "冻结表共 66 条（桥 65 + 通配 AL_* 1）。分探活/内存/扫描/指针/调试/内核六组，具体签名要看单条。"),
    ("kitty_ops 里 S_NEW 的签名是什么？", {"filter": "S_NEW"},
     "OK|S_NEW|<vt>|<val>|<start>|<stop> → OK|scan|range|<n>w|<desc>[|pending]  必须显式区间，窗 ≤16MB",
     "S_NEW|<vt>|<val>|<start>|<stop>，必须给显式区间，单窗 ≤16MB、总 ≤64MB、≤4 窗；回包 pending 表示未落定。"),
    ("P_BACK 的窗口限制是多少？", {"filter": "P_BACK"},
     "OK|P_BACK|<addr>|<start>|<stop> → OK|<n>[|pending]  必须显式窗口，命中上限 200",
     "P_BACK 必须显式窗口，命中上限 200；超了要缩窗。取结果用 P_BACK_RES|<n>。"),
    ("内核面那几个 OP 都是干什么的？", {"filter": "KM_"},
     "OK|KM_API KM_INFO KM_MODE KM_ATTACH KM_R KM_W KM_PA KM_PR KM_PW|KM_PW 默认拒绝（卡死 Lua 引擎）",
     "KM_API 枚举可用面、KM_INFO 看 PEProcess、KM_ATTACH 内核态打开、KM_R/KM_W 路由读写、KM_PA/PR 物理、KM_PW 默认拒绝。"),
    ("DBG_ 开头的 OP 有哪些？", {"filter": "DBG"},
     "OK|DBG_ATTACH DBG_BP DBG_BP_LIST DBG_BP_DEL DBG_GO DBG_REGS DBG_STAT DBG_DETACH DBG_WAIT",
     "调试面 9 条。DBG_ATTACH 是双层闸门（force+unsafe），本 build 走 unsafe 会随机杀宿主，非必要走 C 通道 x64dbg。"),
    ("同步残留怎么清零？", {"filter": "SYNC"},
     "OK|SYNC_STAT → 四项 pending|SYNC_ARCHIVE → 归档",
     "先 SYNC_STAT 看四项 pending，再 SYNC_ARCHIVE 归档，回到全零才开跑新作业。"),
    ("扫描相关一共几个 OP？", {"filter": "S_"},
     "OK|S_NEW S_COUNT S_GET S_NEXT S_FREE S_ABORT S_SNAP S_CHANGED S_UNCHANGED",
     "9 条：精确扫（S_NEW 系）+ 未知初值快照（S_SNAP/S_CHANGED/S_UNCHANGED）。"),
    ("R 和 W 的参数类型都有哪些？", {"filter": "R"},
     "OK|R|<addr>|<byte|word|dword|qword|bytes:len|string:N> → 数值回包十进制 / 字节串十六进制",
     "数值类型回包是十进制，bytes/string 回包是空格分隔的十六进制串 —— 这个坑要记住。"),
    ("地址表 AL_* 怎么用？", {"filter": "AL_"},
     "OK|AL_ADD AL_DEL AL_GET AL_COUNT AL_CLEAR AL_SET_VAL AL_SET_ACT AL_SET_TYPE AL_SET_DESC",
     "9 条。AL_ADD|<描述>|<addr>|<type> 加一条，AL_GET/AL_SET_* 增删改查，AL_COUNT 数条数。"),
    ("LUA 逃生口能用哪些 CE API？", {"filter": "LUA"},
     "OK|LUA|<lua 源码> → 返回≤8192 字符；禁 os.execute/exit/remove、io.popen、require/dofile/loadfile",
     "readBytes/writeBytes/autoAssemble/injectDLL/createRemoteThread 都在；virtualprotect*/getMemoryRanges/setSpeedhack 不在；禁 os.execute 等。"),
]


def tc(i, tool, args):
    return {"id": f"op_{i}", "type": "function",
            "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}


def build_ops(user, args, reply, final, i):
    return {"messages": [
        {"role": "system", "content": SYS},
        {"role": "user", "content": user},
        {"role": "assistant", "content": "", "tool_calls": [tc(i, "kitty_ops", args)]},
        {"role": "tool", "tool_call_id": f"op_{i}", "content": reply},
        {"role": "assistant", "content": final},
    ], "meta": {"kind": "ops-legit"}}


def main():
    tj = json.load(open(TOOLS, encoding="utf-8"))
    tools_schema = tj["function_schemas"]

    # A 工具子集
    A = [json.loads(l) for l in open(V6, encoding="utf-8") if l.strip()]
    print(f"A 工具子集      {len(A)} 条")

    # B kitty_ops 合法用法（带 tools schema）
    B = []
    for i, (u, a, r, f) in enumerate(OPS_LEGIT, 1):
        rec = build_ops(u, a, r, f, i)
        rec["tools"] = tools_schema
        B.append(rec)
    print(f"B ops 合法用法  {len(B)} 条")

    # C 文本子集：w3 全保留 + v5-mix 其余精选
    w3 = [json.loads(l) for l in open(W3, encoding="utf-8") if l.strip()]
    w3_users = {(r["messages"][0]["content"] or "").strip() for r in w3}
    v5 = [json.loads(l) for l in open(V5, encoding="utf-8") if l.strip()]
    C_w3 = [{"messages": r["messages"], "meta": {"kind": "text", "src": "w3-nsfw"}} for r in w3]
    rest = []
    skipped_tool_role = 0
    for r in v5:
        msgs = r.get("messages") or []
        # v5-mix 里有 61 行带 tool 角色，但其 assistant 消息没有 tool_calls 字段（旧格式），
        # 直接混进来会造成 tool_call_id 失配。这些行由 V6 的 615 条规范轨迹覆盖，跳过。
        if any(m.get("role") == "tool" for m in msgs):
            skipped_tool_role += 1
            continue
        u = next(((m.get("content") or "") for m in msgs if m.get("role") == "user"), "")
        if u.strip() in w3_users:
            continue
        rest.append({"messages": msgs, "meta": {"kind": "text", "src": "v5-mix"}})
    print(f"   跳过 v5-mix 里 {skipped_tool_role} 条不规范 tool 行（由 V6 轨迹覆盖）")
    random.Random(20261024).shuffle(rest)
    C_rest = rest[:400]
    C = C_w3 + C_rest
    print(f"C 文本子集      {len(C)} 条（w3 NSFW {len(C_w3)} + v5 通用 {len(C_rest)}）")

    allrows = A + B + C
    random.Random(7).shuffle(allrows)

    # 校验
    names = {x["name"] for x in tj["tools"]}
    acts = {x["name"]: x["actions"] for x in tj["tools"]}
    errs = []
    tcnt = collections.Counter()
    n_tool_rows = 0
    for n, rec in enumerate(allrows):
        if "tools" in rec:
            n_tool_rows += 1
        ids = set()
        for m in rec["messages"]:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for c in m["tool_calls"]:
                    nm = c["function"]["name"]
                    tcnt[nm] += 1
                    if nm not in names:
                        errs.append(f"#{n} 未知工具 {nm}")
                    a = json.loads(c["function"]["arguments"]).get("action")
                    if a is not None and nm in acts and a not in acts[nm]:
                        errs.append(f"#{n} {nm} action={a} 非法")
                    ids.add(c["id"])
            if m.get("role") == "tool" and m.get("tool_call_id") not in ids:
                errs.append(f"#{n} tool_call_id 失配")
        if not rec["messages"] or rec["messages"][-1].get("role") != "assistant":
            errs.append(f"#{n} 末条不是 assistant（train_kitty.py L197 会拒）")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        for r in allrows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total = sum(tcnt.values())
    ops = tcnt.get("kitty_ops", 0)
    print(f"\n写出 {len(allrows)} 条 → {OUT}")
    print(f"带 tools schema 的行  {n_tool_rows}（{n_tool_rows/len(allrows)*100:.1f}%）")
    print(f"校验错误              {len(errs)}")
    for e in errs[:8]:
        print("  ", e)
    print(f"\n工具调用总数 {total}；kitty_ops {ops} = {ops/max(1,total)*100:.2f}%")
    print("  v5 基线: kitty_ops 81/753 = 10.76%")
    print("\n工具频次 Top 12:")
    for nm, c in tcnt.most_common(12):
        print(f"  {nm:<22} {c}")
    for k in ("kitty_jadx", "kitty_rea_trace"):
        print(f"  {k:<22} {tcnt.get(k,0)}")


if __name__ == "__main__":
    main()
