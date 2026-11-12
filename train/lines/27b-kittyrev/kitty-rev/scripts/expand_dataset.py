#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""expand_dataset.py —— 大规模数据扩展（契约驱动，分层标注，不编事实）

输入: contracts/*.json（真实契约）+ data/real_sft.jsonl（真实轨迹）+ data/seed_*.jsonl
输出: data/large/{sft,dpo,eval}.jsonl + data/large/manifest.json

质量分层（meta.tier，训练时可按权重采样）:
  gold    手写种子 + 真实轨迹 + 多轮任务轨迹（行为/动作序列，最贵）
  silver  契约模板生成（签名/回包/坑/路由/错误码/transition），一题一事实
  guard   反例纠正（错误用法 → 正确用法），用于抑制高频错误

设计约束（防止把模板话术学成能力）:
  · silver 只陈述契约原文，契约没写的就说「契约未载明，用 kitty_ops 查」
  · gold 才写判断与序列；序列里的回包形态取自 ops.json 的 reply 字段
  · 所有生成样本 meta.cat + meta.src 可追溯；同 (user, assistant) 全局去重

用法:
  python expand_dataset.py                # 生成全部
  python expand_dataset.py --dry-run      # 只统计
  python expand_dataset.py --variants 8   # 控制 silver 变体乘数（默认 6）
"""
import argparse
import json
import os
import random
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(HERE, "contracts")
DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "large")

# ---------------------------------------------------------------- 契约加载
def jload(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def jlines(p):
    if not os.path.isfile(p):
        return []
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


TOOLS_DOC = jload(os.path.join(CONTRACTS, "tools.json"))
OPS_DOC = jload(os.path.join(CONTRACTS, "ops.json"))
TRANS_DOC = jload(os.path.join(CONTRACTS, "transitions.json"))
TOOLS = TOOLS_DOC["tools"]
OPS = OPS_DOC["ops"]
HOT = OPS_DOC.get("hot", [])
TYPES = TRANS_DOC["types"]
ERRCODES = TRANS_DOC["errCodes"]

TOOL_BY_NAME = {t["name"]: t for t in TOOLS}
OP_BY_NAME = {o["op"]: o for o in OPS}


def sft(user, assistant, cat, tier, **meta):
    return {"messages": [{"role": "user", "content": user},
                         {"role": "assistant", "content": assistant}],
            "meta": {"cat": cat, "tier": tier, **meta}}


# ---------------------------------------------------------------- 1 OP 语法
def op_purpose(o):
    """从 sig/note 推用途（只做关键词映射，不臆造）"""
    note = (o.get("note") or "")
    op = o["op"]
    rules = [
        (("扫描", "S_NEW", "S_NEXT", "S_COUNT", "S_GET", "scan"), "扫描定位数值/地址"),
        (("指针", "P_BACK", "P_WALK"), "指针链反查与回验"),
        (("物理", "KM_PA", "KM_PR", "KM_PW"), "物理地址换算与物理读写"),
        (("内核", "KM_"), "内核路由访问"),
        (("断点", "DBG_BP", "DBG_GO", "DBG_REGS", "DBG_"), "调试面（断点/单步/寄存器）"),
        (("模块", "MODENUM", "MODBASE"), "取模块基址与窗口"),
        (("进程", "LP", "OPEN", "CUR"), "进程枚举与附加"),
        (("写", "W|", "ALLOC", "FREE"), "内存写入与分配"),
        (("读", "R|", "MEMDUMP_HEX"), "内存读取"),
        (("收尾", "SYNC_"), "同步残留归一"),
        (("作业", "JOB_STAT"), "异步作业落定判据"),
        (("地址表", "AL_"), "地址表条目维护"),
        (("Lua", "LUA"), "CE API 逃生口"),
        (("倍速", "SPEED"), "speedhack 倍率"),
    ]
    for keys, label in rules:
        if any(k in op or k in note for k in keys):
            return label
    return "A 通道操作"


OP_Q = [
    ("`{op}` 的参数签名是什么？只给签名与回包，不要展开。",
     "签名：`{sig}`\n回包：{reply}"),
    ("`{op}` 怎么调？给我可以直接发的 op 串。",
     "直接发：`{sig}`\n回包形态：{reply}"),
    ("`{op}` 回包长什么样？我要写解析。",
     "`{op}` 回包：{reply}\n签名：`{sig}`"),
    ("`{op}` 有什么坑？一句话说清。",
     "坑：{note}\n签名：`{sig}`\n回包：{reply}"),
    ("我要{use}，该用哪条 OP、参数怎么给？",
     "用 `{op}`：`{sig}`\n回包：{reply}"),
    ("`{op}` 失败了会给什么码？",
     "`{op}` 失败口径：{note}\n正常回包：{reply}"),
    ("把 `{op}` 的调用写进 BATCH 里，第一行写什么、后面写什么？",
     "BATCH 投递：首行 `SEQ|BATCH`，随后每行一条 OP；本行写 `{sig}`\n回包：{reply}"),
    ("`{op}` 和同族 OP 怎么区分？",
     "`{op}` 的定位：{use}\n签名：`{sig}`\n回包：{reply}"),
]


def gen_op(variants):
    rows = []
    qs = OP_Q[:max(3, min(variants, len(OP_Q)))]
    for o in OPS:
        use = op_purpose(o)
        note = o.get("note") or "（契约未载明额外限制；细节用 kitty_ops filter=" + o["op"] + " 查）"
        for qt, at in qs:
            rows.append(sft(qt.format(op=o["op"], use=use),
                            at.format(op=o["op"], sig=o["sig"], reply=o["reply"], note=note, use=use),
                            "op-syntax", "silver", op=o["op"]))
    return rows


# ---------------------------------------------------------------- 2 工具 × action
ACT_Q = [
    ("`{tool}` 的 action=`{act}` 做什么？参数怎么给？",
     "**{tool}**（{channel}）action=`{act}`：{desc}\n{opsline}失败判据：看回包 `ERR|…`，按码改动作，不换参数连试。"),
    ("我要用 `{tool}` 完成一件事，action 该选哪个？",
     "`{tool}` 支持的 action：{acts}。当前问的 `{act}` 用途：{desc}\n{opsline}先用 status 类只读动作确认环境，再进写动作。"),
    ("`{tool}` action=`{act}` 报错了怎么办？",
     "先读 `ERR|` 后的码：`need-range` 补区间、`no-target` 先 OPEN、`unknown` 用 kitty_ops 查名。\n`{tool}` 的 `{act}` 关联 OP：{opsflat}"),
]


def gen_tool_action(variants):
    rows = []
    qs = ACT_Q[:max(2, min(variants, len(ACT_Q)))]
    for t in TOOLS:
        acts = t["actions"] or ["（无独立 action，按 OP 走）"]
        ops = "、".join(t["ops"]) if t.get("ops") else ""
        opsline = f"关联 OP：{ops}。\n" if ops else ""
        for act in acts:
            for qt, at in qs:
                rows.append(sft(
                    qt.format(tool=t["name"], act=act, desc=t["description"], acts="/".join(t["actions"]) or "无"),
                    at.format(tool=t["name"], act=act, desc=t["description"], channel=t["channel"],
                              opsline=opsline, opsflat=ops or "（该工具不直接下发 OP）",
                              acts="/".join(t["actions"]) or "无"),
                    "tool-action", "silver", tool=t["name"], action=act))
    return rows


# ---------------------------------------------------------------- 3 工具路由
ALT = {
    "kitty_ce": "要发具体 OP（PING/OPEN/R/S_NEW/MODENUM/P_BACK）就用它；不涉及 OP 的编排类任务用更上层的专用工具。",
    "kitty_ops": "不知道 OP 名或语法时查它，不要读源码。",
    "kitty_status": "只想看通道活不活、pending 多少，用它；不要为了探活去 OPEN 目标。",
    "kitty_drv": "宿主进程消失、桥无响应时用它 host 重拉；驱动状态查 ensure/status。",
    "kitty_k X": "",
}


def gen_route(variants):
    rows = []
    qs = [
        ("`{tool}` 什么时候该用，什么时候不该用？", "该用：{desc}。\n该用它的判据：任务落到「{channel}」这条通道上。\n不该用：任务能用更上层的专用工具一步完成时，别下沉到它。\n"),
        ("`{tool}` 和 `kitty_ce` 的分工是什么？", "`{tool}`：{desc}（通道 {channel}）。\n`kitty_ce`：直接下发 A 通道 OP。\n判据：需要精确 OP 语法走 kitty_ce；需要成套编排/解析走 {tool}。\n"),
        ("`{tool}` 不在我的工具集里，怎么办？", "上报，不自造包装。\n`{tool}` 的职责是：{desc}。\n替代路径二选一：① 用同通道里已有的工具（先 kitty_ops 查 OP）；② 请你启用该工具后我再执行。\n"),
        ("一次任务里 `{tool}` 该排在第几步？", "定位：{desc}（通道 {channel}）。\n排序原则：只读探活（status/PING）→ 目标锁定（OPEN/target-set）→ 取数（{tool} 或 kitty_ce）→ 收口（task-dispatch finish → task-close）。\n"),
        ("用 `{tool}` 之前必须先确认什么？", "先确认三件事：① 通道活着（PING/status）；② 目标已锁定（双字段：会话目标 + 目标进程）；③ 参数合法（地址/区间/位数）。\n`{tool}` 自身职责：{desc}。\n"),
    ]
    qs = qs[:max(2, min(variants, len(qs)))]
    for t in TOOLS:
        for qt, at in qs:
            rows.append(sft(qt.format(tool=t["name"], desc=t["description"], channel=t["channel"]),
                            at.format(tool=t["name"], desc=t["description"], channel=t["channel"]),
                            "tool-route", "silver", tool=t["name"]))
    return rows


# ---------------------------------------------------------------- 4 transition
TRANS_DESC = {
    "enter-task": "锁定双字段进任务态（须 sessionGoal + targetProcess）",
    "enter-standby": "回待命并清锁定",
    "stage-start": "开阶段（stage 名）",
    "stage-complete": "关阶段（同 stage，可带 evidence）",
    "stage-fail": "标记阶段失败（stage）",
    "retry-stage": "重试阶段（stage）",
    "block": "阻塞提问（stage + question）",
    "answer": "回答提问（questionId + answer）",
    "complete": "阶段全部完成后收口（evidence 非空）",
    "finish": "一步收口（evidence 非空）——最常用",
    "abandon": "放弃（可选 reason）",
    "set-consent": "设置会话授权（consent）",
}
TRANS_NEED_EVIDENCE = {"finish", "complete"}
TRANS_NEED_FIELD = {
    "enter-task": ("sessionGoal", "targetProcess"),
    "stage-start": ("stage",), "stage-complete": ("stage",), "stage-fail": ("stage",),
    "retry-stage": ("stage",), "block": ("stage", "question"), "answer": ("questionId", "answer"),
    "set-consent": ("consent",),
}


def transition_json(t):
    parts = [f'"type":"{t}"']
    for f in TRANS_NEED_FIELD.get(t, ()):
        parts.append(f'"{f}":"<{f}>"')
    if t in TRANS_NEED_EVIDENCE:
        parts.append('"evidence":["<证据>"]')
    return "{" + ",".join(parts) + "}"


def gen_transition(variants):
    rows = []
    for t in TYPES:
        js = transition_json(t)
        need = TRANS_NEED_FIELD.get(t, ())
        rows.append(sft(f"`task-dispatch` 的 `{t}` 怎么调？给最小 JSON。",
                        f"```json\n{js}\n```\n要点：键名是 type，不是 state；" +
                        (f"必填 {need}；" if need else "") +
                        ("evidence 不能空数组。" if t in TRANS_NEED_EVIDENCE else "无 evidence 要求。"),
                        "transition-syntax", "silver", type=t))
        rows.append(sft(f"`{t}` 这个 transition 是干什么的？什么时候用？",
                        f"**{t}** — {TRANS_DESC.get(t, '')}。\n最小调用：`{js}`",
                        "transition-syntax", "silver", type=t))
        rows.append(sft(f"我把 transition 写成 `{{\"state\":\"{t}\"}}` 报错了，怎么改？",
                        f"键名错了：只认 `type`。改成 `{js}`。\n报错原文通常是 `ERR|TASK-TRANSITION-UNKNOWN`，它会把 12 个合法值全列出来，按列出的值改一次即可。",
                        "transition-syntax", "silver", type=t))
        if variants >= 4:
            rows.append(sft(f"`{t}` 和 `finish` 有什么区别？该用哪个？",
                            f"`{t}`：{TRANS_DESC.get(t, '')}。\n`finish`：一步收口，带 evidence，最常用。\n判据：只想结束当前任务用 finish；需要保留阶段视角才用 stage-* 组合。",
                            "transition-syntax", "silver", type=t))
        if variants >= 6:
            rows.append(sft(f"用 `{t}` 时最容易犯的错是什么？",
                            f"最常见的错：写成 state 键、evidence 给空数组、stage 名和 stage-complete 不一致。\n正确形态：`{js}`",
                            "transition-syntax", "silver", type=t))
    return rows


# ---------------------------------------------------------------- 5 错误码
ERR_FIX = {
    "need-range": ("扫描/反查缺区间", "先 MODENUM 取模块窗口，再用真实 start/stop 重发一次；不要填 0x0–0xFFFFFFFF 全空间。", "MODENUM → S_NEW|vt|val|start|stop"),
    "no-target": ("未附加进程", "先 OPEN|<pid或名>（或 target-get 确认锁定），再重发原指令。", "OPEN|<pid或名> → 原指令"),
    "unknown": ("OP 名不在冻结表", "用 kitty_ops 查最近似名，改一次；不要猜第二遍。", "kitty_ops filter=<前缀> → 改正"),
    "too-big-rescan": ("交集超过重扫上限", "S_GET 取样确认，收窄区间再扫。", "S_GET|0|20 → S_NEXT 收窄"),
    "no-such-pid": ("PID 不存在", "用 LP 取进程表挑真实 pid，或按进程名 OPEN。", "LP → OPEN|<真实pid>"),
    "not-paused": ("未暂停就取寄存器", "先 DBG_BP 命中并 DBG_WAIT，再 DBG_REGS。", "DBG_BP → DBG_WAIT → DBG_REGS"),
    "attach-failed": ("调试附加失败", "不是参数问题：先 kitty_status 判宿主，再改走 C 通道 x64dbg。", "kitty_status probe=true → kitty_x64dbg selftest"),
    "attach-requires-unsafe-flag": ("双层闸门未开", "DBG_ATTACH 需要 force+unsafe；本 build 走 unsafe 会杀宿主，非必要不试，改走 C 通道。", "kitty_x64dbg seed/rununtil"),
    "debug-attach-unsupported": ("该 build 不支持调试附加", "换 C 通道真调试。", "kitty_x64dbg selftest"),
    "TASK-TRANSITION-UNKNOWN": ("transition type 不合法", "键名只有 type；按报错列出的 12 个值改一次。", "task-dispatch {\"type\":\"finish\",\"evidence\":[...]}"),
    "TASK-TRANSITION-INVALID": ("transition 字段缺失/多余", "按类型补必填字段（finish/complete 要 evidence）。", "task-dispatch 带 evidence"),
    "EARLY-EXIT-DENY": ("任务还是 none 态", "用 finish / abandon / enter-standby 之一解锁，别重复 complete。", "task-dispatch {\"type\":\"finish\",\"evidence\":[...]}"),
    "MODE-NEEDS-DUAL": ("切任务态缺双字段", "先 ask 选择题定会话目标 + target-set 落盘，再 mode-set task。", "target-set target+sessionGoal → mode-set task"),
    "HOST-MISMATCH-DENY": ("状态来自另一台机器", "按本机重锁：host-rebind 或 target-set 重写。", "kitty_settings host-rebind"),
    "SESSION-KEY-MISSING": ("会话键缺失", "新会话不自动继承；显式 target-set。", "kitty_settings target-set"),
    "TASK-DISPATCH-MISSING": ("没有可用任务", "先 task-open / enter-task。", "task-open → task-dispatch"),
    "TASK-MIRROR-FAILED": ("镜像写失败", "重读真相源确认落盘，再决定是否重试一次。", "target-get → 重试 target-set"),
    "inherit-host-mismatch": ("跨会话继承来源机不一致", "显式 from=<sessionKey> 或重锁。", "task-inherit from=<sessionKey>"),
    "STANDBY-DENY": ("待命态拒绝执行", "双字段未齐：先 ask 选择题 + target-set，转任务态再跑。", "ask → target-set → 重发指令"),
    "no-target-standby": ("待命态无目标", "同上：先锁双字段。", "target-set → 重发"),
}


def gen_err(variants):
    rows = []
    for code in ERRCODES:
        hit = None
        for k, v in ERR_FIX.items():
            if k.lower() == code.lower() or k.lower() in code.lower():
                hit = v
                break
        if not hit:
            continue
        meaning, fix, seq = hit
        rows.append(sft(f"工具返回 `ERR|{code}`，我下一步该做什么？",
                        f"判定：{meaning}。\n正确下一步：{fix}\n动作序列：`{seq}`\n禁止：换参数连试、换 op 穷举、自造包装脚本。",
                        "error-recovery", "silver", err=code))
        rows.append(sft(f"`ERR|{code}` 是什么意思？会不会是我参数写错了？",
                        f"{meaning}。{'多数情况不是参数错，是前置状态没满足。' if 'PID' not in code and 'range' not in code else '这条通常和参数直接相关。'}\n处置：{fix}",
                        "error-recovery", "silver", err=code))
        if variants >= 3:
            rows.append(sft(f"连续两次 `ERR|{code}`，还要继续试吗？",
                            f"不要再试。第二次同样的码说明前置条件没变：{fix}\n按 `{seq}` 走一次；仍失败就向操作者汇报当前状态与阻塞点（这是收敛，不是放弃）。",
                            "error-recovery", "silver", err=code))
    return rows
