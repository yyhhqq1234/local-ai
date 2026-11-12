#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_dataset.py —— 用真实 kitty 契约 + 手写种子，生成 SFT / DPO 数据集

输入（相对 train/lines/27b-kittyrev/kitty-rev）:
  contracts/tools.json         64 个 kitty 工具（name/channel/actions/ops/description）
  contracts/ops.json           66 条 A 通道 OP（op/sig/reply/note）+ hot
  contracts/transitions.json   12 个 taskTransition type + 28 个 ERR| 码
  data/seed_sft.jsonl          手写行为种子（真值，权重最高）
  data/seed_dpo.jsonl          手写偏好对

输出:
  data/train.jsonl   SFT 训练集
  data/eval.jsonl    SFT 验收集（按 category 分层留出，不参与训练）
  data/dpo.jsonl     DPO 偏好对（种子 + 模板扩展）
  data/stats.json    计数与类别分布（写报告用）

原则:
  · 模板扩展只做「语法接地」（OP 签名 / 工具路由 / 错误码→正确动作），一条一事实，不编数字
  · 行为类（上报 / 收敛 / 收口 / 压缩）只用手写种子，不模板化，避免把空话学成话术
  · 全部样本带 meta.cat，便于分档加权与验收统计

用法:
  python build_dataset.py            # 生成
  python build_dataset.py --dry-run  # 只统计不落盘
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(HERE, "contracts")
DATA = os.path.join(HERE, "data")

TOOL_SYS = "逆向工作台。可用工具：kitty_ce / kitty_ops / kitty_settings / kitty_status / read / write / ops_bash。"


def jload(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def jlines(p):
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] {os.path.basename(p)}:{i} 解析失败 {e}")
    return out


def sft(user, assistant, cat, **meta):
    m = {"messages": [{"role": "user", "content": user},
                      {"role": "assistant", "content": assistant}],
         "meta": {"cat": cat, **meta}}
    return m


# ---------------- 模板扩展 1: OP 语法接地 ----------------
def gen_op_samples(ops_doc):
    """每条 OP → 一条「签名/回包/坑」问答。取真实 sig/reply/note，不编。"""
    out = []
    for o in ops_doc["ops"]:
        op, sig, reply, note = o["op"], o["sig"], o["reply"], o.get("note", "")
        if not reply:
            continue
        body = [f"`{sig}`", f"回包：{reply}"]
        if note:
            body.append(f"坑：{note}")
        out.append(sft(
            f"kitty A 通道 `{op}` 的参数签名、回包和已知坑是什么？一条答完。",
            f"**{op}**\n" + "\n".join(f"- {b}" for b in body),
            "op-syntax", op=op,
        ))
    return out


# ---------------- 模板扩展 2: 工具路由 ----------------
ROUTE_INTENT = {
    "kitty_ce": "直接执行 A 通道 OP（探活/进程/内存/模块/扫描/指针/调试）",
    "kitty_ops": "查 A 通道 OP 冻结表（不知道 op 语法时先查，不要读源码）",
    "kitty_status": "只读看桥健康（PING/时戳/pending），不改任何状态",
    "kitty_drv": "驱动与宿主守护：宿主消失 → host 单实例重拉",
    "kitty_init": "一键双绿初始化（提权后跑，改完重启宿主）",
    "kitty_variants": "切换驱动/CE/DBG 变体，list 先看功能与检测面证据等级",
    "kitty_km": "内核路由读写 / VA→PA / 物理读（写物理已被永久拒绝）",
    "kitty_dualview": "同一地址三视图取数门禁（R / KM_R / KM_PR）",
    "kitty_acescan": "反作弊对抗日一键编排（门禁+写回环+证据包）",
    "kitty_wpb": "写保护绕过（PTE 直改，仅用户态地址，写后还原）",
    "kitty_pchain": "多跳指针链反查（P_BACK+R+P_WALK 一条龙）",
    "kitty_sym": "PE 导出/导入解析与符号地址解析（文件或内存）",
    "kitty_patch": "PE 静态补丁（info/find/patch/rollback，expect 拒写）",
    "kitty_asm": "x64 迷你汇编（jz→jmp 之类字节生成与 rel 修正）",
    "kitty_dump": "内存转储 + 按节表重建磁盘格式镜像",
    "kitty_inject": "DLL 注入（ce / ps / loaddll 三档）",
    "kitty_prot": "内存保护改档（rwx 等）与读写探针",
    "kitty_x64dbg": "真调试（C 通道）：断点/单步/寄存器/日志采集",
    "kitty_dbg": "A 通道调试面（attach 有双层闸门，本 build 会杀宿主，慎用）",
    "kitty_settings": "会话真相源：target-set/target-get/mode-get/task-dispatch/task-close/trail-get",
    "kitty_trail": "探索日志道（每次动作写一条，收口时可回溯）",
    "kitty_selftest": "回归自检 a/c/e/all",
    "kitty_loop": "夜跑一轮 8 站流水线（收案→分诊→静态→定位→对抗→还原→修改→回归）",
}


def gen_tool_samples(tools_doc):
    out = []
    for t in tools_doc["tools"]:
        name = t["name"]
        acts = "/".join(t["actions"]) if t["actions"] else "（无 action）"
        intent = ROUTE_INTENT.get(name, t["description"])
        ops = "、".join(t["ops"][:8]) if t.get("ops") else ""
        lines = [f"**{name}** — {t['description']}",
                 f"- 通道：{t['channel']}",
                 f"- action：{acts}"]
        if ops:
            lines.append(f"- 关联 OP：{ops}")
        lines.append(f"- 什么时候用：{intent}")
        out.append(sft(
            f"`{name}` 是干什么的、什么时候该用它而不是别的 kitty 工具？",
            "\n".join(lines), "tool-route", tool=name,
        ))
    return out


# ---------------- 模板扩展 3: 错误码 → 正确动作 ----------------
ERR_FIX = {
    "need-range": "S_NEW / P_BACK 必须给显式区间。先 MODENUM 取模块窗口，再用真实 start/stop 重发一次；不要换成全空间或换 op。",
    "no-target": "会话未附加进程。先 OPEN|<pid或名>（或 target-get 确认锁定），再重发原指令；地址本身大概率没问题。",
    "unknown": "OP 名不在冻结表。用 kitty_ops 查最近似名，改一次；不要猜第二遍。",
    "too-big-rescan": "S_NEXT 交集超上限。先 S_GET 取样确认，再收窄区间重扫。",
    "no-such-pid": "PID 不存在。用 LP 取进程表挑真实 pid，或按进程名 OPEN。",
    "not-paused": "DBG_REGS 需要先暂停。DBG_BP + DBG_WAIT 命中后再取寄存器。",
    "attach-failed": "附加失败不是参数问题：先 kitty_status 判宿主，再考虑 C 通道 x64dbg。",
    "TASK-TRANSITION-UNKNOWN": "transition 只认 type 键，不认 state。合法 12 类；收口用 {\"type\":\"finish\",\"evidence\":[...]}。",
    "EARLY-EXIT-DENY": "任务仍是 none 态。用 finish / abandon / enter-standby 三者之一解锁，别重复 complete。",
    "MODE-NEEDS-DUAL": "切任务态要求双字段齐。先 ask 选择题定会话目标 + target-set 落盘，再 mode-set task。",
    "target-set": "target-set 缺 sessionGoal 或 target。两个字段一起给，单字段不落盘。",
    "SYNC": "跑批前 SYNC_STAT 四项必须归零；先 SYNC_ARCHIVE 归档残留。",
}


def gen_err_samples(trans_doc):
    out = []
    for code in trans_doc.get("errCodes", []):
        fix = None
        for key, v in ERR_FIX.items():
            if key.lower() in code.lower():
                fix = v
                break
        if not fix:
            continue
        out.append(sft(
            f"工具返回 `ERR|{code}`，下一步该做什么？只给一个动作序列。",
            f"判定：`ERR|{code}`\n\n正确下一步：{fix}\n\n禁止：换参数连试、换 op 穷举、自造包装脚本。",
            "error-recovery", err=code,
        ))
    return out


# ---------------- 模板扩展 4: transition 用法 ----------------
TRANS_DESC = {
    "enter-task": "锁定双字段进任务态（须 sessionGoal + targetProcess）",
    "enter-standby": "回待命（清锁定）",
    "stage-start": "开阶段（stage 名）",
    "stage-complete": "关阶段（同 stage，可带 evidence）",
    "stage-fail": "阶段失败（stage）",
    "retry-stage": "重试阶段（stage）",
    "block": "阻塞提问（stage + question）",
    "answer": "回答提问（questionId + answer）",
    "complete": "阶段全完成后收口（evidence 非空）",
    "finish": "一步收口（evidence 非空）——最常用",
    "abandon": "放弃（可选 reason）",
    "set-consent": "设置会话授权（consent）",
}


def gen_transition_samples(trans_doc):
    out = []
    for t in trans_doc.get("types", []):
        desc = TRANS_DESC.get(t, "")
        out.append(sft(
            f"`task-dispatch` 的 transition type `{t}` 怎么用？给最小可执行 JSON。",
            f"**{t}** — {desc}\n\n最小调用：\n```json\n{{\"type\":\"{t}\"" +
            (",\"evidence\":[\"<证据>\"]" if t in ("finish", "complete") else "") +
            "}\n```\n\n注意：键名是 type，不是 state。" + ("finish/complete 的 evidence 不能是空数组。" if t in ("finish", "complete") else ""),
            "transition-syntax", type=t,
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--eval-ratio", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=20261020)
    a = ap.parse_args()

    need = ["tools.json", "ops.json", "transitions.json"]
    missing = [n for n in need if not os.path.isfile(os.path.join(CONTRACTS, n))]
    if missing:
        print(f"[FATAL] 缺契约 {missing}；先跑 node scripts/extract_contracts.mjs")
        sys.exit(1)

    tools_doc = jload(os.path.join(CONTRACTS, "tools.json"))
    ops_doc = jload(os.path.join(CONTRACTS, "ops.json"))
    trans_doc = jload(os.path.join(CONTRACTS, "transitions.json"))

    seed_sft = jlines(os.path.join(DATA, "seed_sft.jsonl"))
    seed_dpo = jlines(os.path.join(DATA, "seed_dpo.jsonl"))
    real_sft = jlines(os.path.join(DATA, "real_sft.jsonl")) if os.path.isfile(os.path.join(DATA, "real_sft.jsonl")) else []

    generated = []
    generated += gen_op_samples(ops_doc)
    generated += gen_tool_samples(tools_doc)
    generated += gen_err_samples(trans_doc)
    generated += gen_transition_samples(trans_doc)

    # 去重（user+assistant 完全一致）
    seen, uniq = set(), []
    for s in seed_sft + real_sft + generated:
        msgs = s["messages"]
        key = (msgs[0]["content"][:200], msgs[1]["content"][:200])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)

    # 分层留出 eval（种子行为类全部进 train，验证集只从模板与种子里抽少量）
    rnd = random.Random(a.seed)
    by_cat = {}
    for s in uniq:
        by_cat.setdefault(s["meta"]["cat"], []).append(s)
    train, evalset = [], []
    for cat, rows in by_cat.items():
        rnd.shuffle(rows)
        k = max(1, int(len(rows) * a.eval_ratio)) if len(rows) >= 4 else 0
        evalset += rows[:k]
        train += rows[k:]
    rnd.shuffle(train)
    rnd.shuffle(evalset)

    dpo = list(seed_dpo)

    stats = {
        "contracts": {"tools": tools_doc["count"], "ops": ops_doc["count"],
                      "transitions": trans_doc["count"], "errCodes": len(trans_doc.get("errCodes", []))},
        "bridge": ops_doc.get("bridge"),
        "sft_total": len(train) + len(evalset),
        "sft_train": len(train),
        "sft_eval": len(evalset),
        "dpo": len(dpo),
        "by_cat": {c: len(v) for c, v in sorted(by_cat.items(), key=lambda x: -len(x[1]))},
        "avg_assistant_chars": round(sum(len(s["messages"][1]["content"]) for s in train) / max(1, len(train)), 1),
    }

    print(json.dumps(stats, ensure_ascii=False, indent=2))

    if a.dry_run:
        print("[dry-run] 未落盘")
        return

    def dump(path, rows):
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    dump(os.path.join(DATA, "train.jsonl"), train)
    dump(os.path.join(DATA, "eval.jsonl"), evalset)
    dump(os.path.join(DATA, "dpo.jsonl"), dpo)
    with open(os.path.join(DATA, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"[ok] train={len(train)} eval={len(evalset)} dpo={len(dpo)} → {DATA}")


if __name__ == "__main__":
    main()
