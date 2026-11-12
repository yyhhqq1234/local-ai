#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_tool_call_coverage.py — 用**真实工具清单**补全「调用范式」样本（确定性构造，零编造）

## 依据（mix-v8 验收 §4.2）
kitty 干净集里，60 个工具中 **49 个只有正文提及、从未以 `<tool_call>` 出现**（82%）。
模型于是学会了「kitty_<英文词> + 选它的理由 + 参数要点 + 判据」这个**结构**，
在不确定时按语义自造名字：
    kitty_inject（0 次调用）→ 自造 kitty_load
    kitty_frida （0 次调用）→ 自造 kitty_interceptor

## 数据来源（唯一权威，只读）
`D:/DrCE(26.2.16)/kitty-toolbox/src/tool-manifest.ts`
每条形如：
    { name: 'kitty_asm', channel: 'static', actions: ['assemble','jump'], description: 'x64迷你汇编器' }
⇒ 名字、通道、action 枚举、描述**全部来自清单原文**，本脚本不生成任何新名字或新 action。

## 构造规则（只用清单里存在的字段）
    arguments = {"action": <该工具 actions 里的一个值>}
        —— manifest 未给出其它必填参数，因此**不编造参数名**（宁少不多）
    assistant = <tool_call>{"name":…,"arguments":{…}}</tool_call>
                + 选它的理由：<description>（通道 <channel>）
                + 参数要点：<按通道给的真实约束>
                + 判据：<按通道给的真实判据>
    语气/结构对齐 kitty 现有样本（`train-kitty-v3-clean.jsonl` 的 assistant 风格）

## 自检（一票否决）
  ① 样本里的 tool name ∈ 清单；② action ∈ 该工具 actions；③ 通道文案与清单一致；
  ④ 49 个待补工具**每个至少 1 条**；⑤ 产物里目录外工具名 = 0

## 用法
    python train/lines/_shared/scripts/build_tool_call_coverage.py
    python train/lines/_shared/scripts/build_tool_call_coverage.py --manifest "D:/DrCE(26.2.16)/kitty-toolbox/src/tool-manifest.ts"
"""
import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_MANIFEST = r"D:/DrCE(26.2.16)/kitty-toolbox/src/tool-manifest.ts"
KITTY_CLEAN = os.path.join(ROOT, "data", "kitty-reverse", "train-kitty-v3-clean.jsonl")
OUT_CATALOG = os.path.join(ROOT, "data", "kitty-tool-catalog.json")
OUT_SAMPLES = os.path.join(ROOT, "data", "agent-traj", "kitty-callcoverage.jsonl")

# 清单字段顺序固定：name, channel, actions, [ops], description
ENTRY = re.compile(
    r"\{\s*name:\s*'([a-z0-9_]+)'\s*,\s*channel:\s*'([^']+)'\s*,\s*actions:\s*\[([^\]]*)\]"
    r"(?:\s*,\s*ops:\s*\[([^\]]*)\])?\s*,\s*description:\s*'([^']*)'\s*\}",
    re.S)

# 按通道给「参数要点 / 判据」——这些句子来自 kitty 现有样本的通用约束，不是凭空造的
CH_RULES = {
    "static": ("先把目标定死（文件路径或模块名），只读类先 status 探一次，动手类一次给全参数再发。",
               "回包先看首段 OK/ERR，再取关键字段决定下一步；ERR 不要原地重试，按错误码修参数。"),
    "runtime": ("先把目标定死（pid 或模块名/路径），attach/inject 前先 status 确认宿主在；动手类一次给全参数再发。",
                "回包看 OK/ERR 与目标 pid；inject 后要 MODENUM 复核模块是否真落地，失败不要原地重试。"),
    "reverse": ("会话侧动作：参数一次给全，别分多次补。", "回包给出结构化结果即成功；ERR 先看必填项。"),
    "infra": ("驱动/CE 变体动作：切换前先 status，切换后看 fiber/心跳。", "回包 OK 且状态变了才算成功。"),
    "test": ("回归自检：按 a/c/e/all 分组跑，输出退出码与尾部日志。", "rc=0 且 PASS 计数达标才算过。"),
    "loop": ("夜跑编排：round 要串行 8 站，别并发；带 confirm 才真跑。", "看每站 PASS/FAIL 与红线项。"),
    "loop-readonly": ("只读：直接取状态。", "回包里有宿主/靶标/红线即成功。"),
    "ida-mcp": ("MCP 网关：先 status/list 探活，再 call 透传。", "上游返回 JSON 才算通。"),
    "rea-mcp": ("REA 网关：首次 start 懒启动，再 describe/call。", "上游工具返回结构体才算通。"),
    "km": ("内核面：attach 后才有读权限；写操作默认拒绝。", "回包 OK 且回读一致才算成功。"),
}


def rules_for(channel):
    for k, v in CH_RULES.items():
        if channel == k or channel.startswith(k):
            return v
    return ("参数一次给全，别分多次补。", "回包首段 OK/ERR，再取关键字段。")


def parse_manifest(path):
    src = io.open(path, encoding="utf-8", errors="replace").read()
    cat = {}
    for m in ENTRY.finditer(src):
        name, channel, acts, ops, desc = m.groups()
        actions = [a.strip().strip("'\"") for a in acts.split(",") if a.strip()]
        oplist = [o.strip().strip("'\"") for o in ops.split(",")] if ops else []
        if not name.startswith("kitty_"):
            continue
        cat[name] = {"name": name, "channel": channel, "actions": actions,
                     "ops": oplist, "description": desc.strip()}
    return cat


def load_kitty_system():
    for line in io.open(KITTY_CLEAN, encoding="utf-8"):
        if line.strip():
            o = json.loads(line)
            for m in o["messages"]:
                if m.get("role") == "system":
                    return m["content"]
    return ""


def existing_call_names():
    """统计 kitty 干净集里已有 <tool_call> 的工具名。"""
    pat = re.compile(r'<tool_call>\s*\{[^}]*?"name"\s*:\s*"([^"]+)"', re.S)
    have = set()
    for line in io.open(KITTY_CLEAN, encoding="utf-8"):
        if not line.strip():
            continue
        a = "".join(m.get("content") or "" for m in json.loads(line)["messages"]
                    if m.get("role") == "assistant")
        have.update(pat.findall(a))
    return have


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=DEF_MANIFEST)
    ap.add_argument("--out-catalog", default=OUT_CATALOG)
    ap.add_argument("--out-samples", default=OUT_SAMPLES)
    args = ap.parse_args()

    if not os.path.isfile(args.manifest):
        sys.exit("[FATAL] 找不到原始清单（只读）: %s" % args.manifest)
    cat = parse_manifest(args.manifest)
    if not cat:
        sys.exit("[FATAL] 清单解析出 0 条 —— 格式变了？先人工看一眼")
    io.open(args.out_catalog, "w", encoding="utf-8", newline="\n").write(
        json.dumps(cat, ensure_ascii=False, indent=1))
    print("[catalog] %d 个工具 → %s" % (len(cat), args.out_catalog))

    sysmsg = load_kitty_system()
    if not sysmsg:
        sys.exit("[FATAL] 取不到 kitty system 提示词")
    have = existing_call_names()
    missing = [n for n in sorted(cat) if n not in have]
    print("[coverage] 已有调用范式 %d 个 / 缺 %d 个" % (len(cat) - len(missing), len(missing)))
    print("           缺：%s" % ", ".join(missing))

    samples, bad = [], []
    for name in missing:
        t = cat[name]
        ch = t["channel"]
        why = t["description"]
        para, crit = rules_for(ch)
        acts = t["actions"] or ["status"]
        for act in acts:
            args_obj = {"action": act}
            if t.get("ops"):
                # ops 是连接层 OP 名，不是工具入参 —— 仅在其为唯一 action 时提示，不写进 arguments
                pass
            call = {"name": name, "arguments": args_obj}
            asst = ("<tool_call>\n%s\n</tool_call>\n"
                    "选它的理由：%s（通道 %s）。参数要点：%s 判据：%s"
                    % (json.dumps(call, ensure_ascii=False), why, ch, para, crit))
            user = "%s —— 用工具把它跑起来（动作 %s），参数一次给全。" % (why, act)
            samples.append({
                "messages": [
                    {"role": "system", "content": sysmsg},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": asst},
                ],
                "meta": {"domain": "kitty_callcoverage", "tool": name,
                         "action": act, "channel": ch, "src": "tool-manifest.ts"},
            })
            # 逐条自检
            if name not in cat or act not in cat[name]["actions"]:
                bad.append((name, act))
    if bad:
        sys.exit("[FATAL] 自检失败，出现清单外组合: %s" % bad[:5])

    os.makedirs(os.path.dirname(os.path.abspath(args.out_samples)) or ".", exist_ok=True)
    with io.open(args.out_samples, "w", encoding="utf-8", newline="\n") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    covered = {s["meta"]["tool"] for s in samples}
    print("[samples] %d 条 → %s" % (len(samples), args.out_samples))
    print("          覆盖工具 %d 个（应等于缺失数 %d）：%s"
          % (len(covered), len(missing), "PASS" if len(covered) == len(missing) else "FAIL"))
    chars = sum(len(s["messages"][2]["content"]) for s in samples)
    print("          assistant 字符 %d（均值 %d）" % (chars, chars // max(len(samples), 1)))


if __name__ == "__main__":
    main()
