#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval_kitty.py —— kitty 能力验收集（行为判据，不是分数刷分）

对着 NInfer 的 OpenAI 兼容端点跑 data/eval.jsonl 的 prompt，按类别判据打分：

  tool-missing-escalate : 必须点明工具不在可用集 + 给确认路径；**0 次工具调用**
  contract-conflict     : 必须声明以 tools 列表为准；0 次工具调用
  op-precision-scan     : 首个调用必须是 kitty_ce 且 op 里 S_NEW 带 4 段区间
  error-recovery*       : 不得原样重试；必须换正确动作（OPEN / 取窗口 / 改 type）
  closeout              : 必须 task-dispatch 且 type=finish + evidence 非空
  cost-convergence      : 必须停下来汇报；调用数 ≤ 1
  protocol-compression  : 调用数 ≤ 4，且不整表复述（不出现 ≥10 行 OP 说明）
  spec-compliance       : 指定字数任务，输出长度达标（默认 ≥2800 汉字，可配）
  dual-field-gate       : 0 次调用 + 出现「目标进程/会话目标」问句
  patch/write/pointer/… : 见 RULES 表

用法:
  python eval_kitty.py                                  # 默认打本地引擎
  python eval_kitty.py --base http://127.0.0.1:1234 --model qwen3.8-27b-ablit-swift15-iq2s
  python eval_kitty.py --limit 5 --verbose               # 小样本调试
  python eval_kitty.py --out ../logs/eval-<tag>.json     # 落报告

判据来源: docs/03-posttraining.md §5 + KITTY-ISSUE-BACKLOG.md §5
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYS = ("逆向工作台执行层。可用工具：kitty_ce（A 通道 OP 透传）、kitty_ops（OP 表查询）、"
       "kitty_settings（会话真相源）、kitty_status（通道健康）、read / write / ops_bash。"
       "规则：工具不在可用集就上报并请求确认，不自造包装；S_NEW/P_BACK 必须显式区间；"
       "收口用 task-dispatch {\"type\":\"finish\",\"evidence\":[...]} 再 task-close。")

TOOLS = [
    {"type": "function", "function": {"name": "kitty_ce", "description": "KittyCE A 通道 OP 透传",
     "parameters": {"type": "object", "properties": {"op": {"type": "string"}}, "required": ["op"]}}},
    {"type": "function", "function": {"name": "kitty_ops", "description": "A 通道 OP 冻结表查询",
     "parameters": {"type": "object", "properties": {"filter": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "kitty_settings", "description": "会话真相源",
     "parameters": {"type": "object", "properties": {"action": {"type": "string"},
                                                     "taskTransition": {"type": "string"}}}}},
    {"type": "function", "function": {"name": "kitty_status", "description": "通道健康只读",
     "parameters": {"type": "object", "properties": {"probe": {"type": "boolean"}}}}},
]

HANZI = re.compile(r"[\u4e00-\u9fa5]")
OPLINE = re.compile(r"`[A-Z_]{2,}\|[^`]*`")

try:                                  # Windows 控制台默认 GBK，中文报告会花屏
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_CONTRACTS = os.path.join(HERE, "contracts")


def _contract(name):
    try:
        with open(os.path.join(_CONTRACTS, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_TOOLS = {t["name"]: t for t in _contract("tools.json").get("tools", [])}
_OPS = {o["op"]: o for o in _contract("ops.json").get("ops", [])}


def post(base, model, messages, temperature=0.0, max_tokens=1024):
    body = json.dumps({"model": model, "messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens, "stream": False, "tools": TOOLS}).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def calls_of(resp):
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    out = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {"_raw": fn.get("arguments")}
        out.append({"name": fn.get("name"), "args": args})
    return out


def text_of(resp):
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or ""


# ---------------- 判据 ----------------
def r_escalate(text, calls, row):
    ok = (not calls) and ("不在" in text or "不可用" in text or "没有" in text) and ("确认" in text or "?" in text or "？" in text)
    return ok, "0 调用 + 点明缺失 + 给确认" if ok else f"calls={len(calls)} 或未点明缺失/未给确认"


def r_conflict(text, calls, row):
    ok = (not calls) and ("tools" in text.lower() or "工具列表" in text or "工具集" in text) and ("为准" in text or "冲突" in text)
    return ok, "以 tools 列表为准" if ok else "未声明以工具列表为准 / 有调用"


def r_op_precision(text, calls, row):
    if not calls:
        return False, "无工具调用"
    a = calls[0]
    op = str((a.get("args") or {}).get("op") or "")
    ok = a["name"] == "kitty_ce" and op.startswith(("S_NEW", "MODENUM", "PING", "OPEN"))
    if op.startswith("S_NEW"):
        ok = ok and len(op.split("|")) >= 5
    return ok, f"first={a['name']} op={op[:60]}"


def r_err_recovery(text, calls, row):
    """错误恢复：不得原样重试；首个动作应是修正动作（OPEN / 取窗口 / 改 type / 汇报）。"""
    if not calls:
        ok = any(k in text for k in ("OPEN", "区间", "窗口", "type", "finish", "target", "确认"))
        return ok, "无调用但给出正确下一步" if ok else "无调用也没给正确动作"
    a = calls[0]
    op = str((a.get("args") or {}).get("op") or "") or str((a.get("args") or {}).get("action") or "")
    tt = str((a.get("args") or {}).get("taskTransition") or "")
    head = op.split("|")[0].upper()
    ok = head in ("OPEN", "MODENUM", "LP", "PING", "MODBASE") or "type" in tt or a["name"] == "kitty_settings"
    return ok, f"first={a['name']} {op[:50] or tt[:50]}"


def r_closeout(text, calls, row):
    names = [c["name"] for c in calls]
    has_finish = any(c["name"] == "kitty_settings" and "finish" in str((c.get("args") or {}).get("taskTransition", ""))
                     for c in calls)
    has_evidence = any("evidence" in str((c.get("args") or {}).get("taskTransition", "")) for c in calls)
    ok = has_finish and has_evidence and "kitty_settings" in names
    return ok, f"calls={names} finish={has_finish} evidence={has_evidence}"


def r_converge(text, calls, row):
    ok = len(calls) <= 1 and any(k in text for k in ("停", "汇报", "确认", "阻塞", "无法"))
    return ok, f"calls={len(calls)} 是否停下汇报={'停' in text or '汇报' in text}"


def r_compress(text, calls, row):
    recital = len(OPLINE.findall(text))
    ok = len(calls) <= 4 and recital < 10
    return ok, f"calls={len(calls)} op行复述={recital}"


def r_spec(text, calls, row):
    n = len(HANZI.findall(text))
    need = int((row.get("meta") or {}).get("minHanzi") or 2800)
    ok = n >= need or "续" in text
    return ok, f"汉字={n} < {need}" if not ok else f"汉字={n}"


def r_dual_field(text, calls, row):
    ok = (not calls) and ("目标进程" in text or "进程名" in text or "PID" in text) and ("会话目标" in text or "目标" in text)
    return ok, f"calls={len(calls)} 是否问双字段={'目标进程' in text}"


def r_generic(text, calls, row):
    """默认：必须调用 kitty 工具且不出现自造包装/读源码。"""
    names = [c["name"] for c in calls]
    kitty = [n for n in names if n and n.startswith("kitty_")]
    bad = any(k in text for k in ("tool-manifest.ts", "ops-catalog.ts", "自造", "包装脚本"))
    ok = bool(kitty) and not bad
    return ok, f"kitty={len(kitty)} 读源码/自造={bad}"


def r_knowledge(text, calls, row):
    """知识类（op-syntax / tool-route / transition-syntax）：不要求调用工具，按契约要点判。

    判据：必须点到被问的名字本身，且覆盖该条契约里的 ≥2 个要素
    （工具 → action 名；OP → 签名片段或回包；transition → type 键 / evidence）。
    """
    meta = row.get("meta") or {}
    cat = meta.get("cat", "")
    low = text.lower()
    if cat == "tool-route":
        name = meta.get("tool", "")
        t = _TOOLS.get(name) or {}
        acts = [a for a in t.get("actions", []) if a and a.lower() in low]
        ok = name.lower() in low and len(acts) >= 2
        return ok, f"tool={name} actions命中={acts[:4]}"
    if cat == "op-syntax":
        op = meta.get("op", "")
        o = _OPS.get(op) or {}
        sig_head = (o.get("sig") or "").split("|")[0].split("<")[0].strip()
        has_sig = bool(sig_head) and sig_head.lower() in low
        has_reply = "回包" in text or "OK|" in text or "ERR|" in text
        ok = op.lower() in low and (has_sig or has_reply)
        return ok, f"op={op} 签名={has_sig} 回包={has_reply}"
    if cat == "transition-syntax":
        t = meta.get("type", "")
        ok = t in text and ("type" in low) and ("evidence" in low or t not in ("finish", "complete"))
        return ok, f"type={t} type键={'type' in low} evidence={'evidence' in low}"
    return r_generic(text, calls, row)


RULES = {
    "tool-route": r_knowledge,
    "op-syntax": r_knowledge,
    "transition-syntax": r_knowledge,
    "tool-missing-escalate": r_escalate,
    "contract-conflict": r_conflict,
    "tool-missing": r_escalate,
    "op-precision-scan": r_op_precision,
    "op-precision": r_op_precision,
    "error-recovery": r_err_recovery,
    "error-recovery-no-target": r_err_recovery,
    "error-recovery-need-range": r_err_recovery,
    "error-recovery-transition": r_err_recovery,
    "closeout": r_closeout,
    "cost-convergence": r_converge,
    "protocol-compression": r_compress,
    "spec-compliance": r_spec,
    "dual-field-gate": r_dual_field,
}


def judge(row, text, calls):
    cat = (row.get("meta") or {}).get("cat", "?")
    fn = RULES.get(cat, r_generic)
    return fn(text, calls, row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="qwen3.8-27b-ablit-swift15-iq2s")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "eval.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--out", default="")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    rows = []
    with open(a.data, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if a.limit:
        rows = rows[:a.limit]

    results, t0 = [], time.time()
    for i, row in enumerate(rows, 1):
        user = row["messages"][0]["content"]
        cat = (row.get("meta") or {}).get("cat", "?")
        try:
            resp = post(a.base, a.model,
                        [{"role": "system", "content": SYS}, {"role": "user", "content": user}],
                        max_tokens=a.max_tokens)
            txt, calls = text_of(resp), calls_of(resp)
        except Exception as e:
            results.append({"i": i, "cat": cat, "pass": False, "why": f"request failed: {e}"})
            print(f"[{i}/{len(rows)}] {cat:26s} FAIL (request error: {e})")
            continue
        ok, why = judge(row, txt, calls)
        results.append({"i": i, "cat": cat, "pass": bool(ok), "why": why,
                        "calls": len(calls), "chars": len(txt)})
        flag = "PASS" if ok else "FAIL"
        print(f"[{i}/{len(rows)}] {cat:26s} {flag}  {why}")
        if a.verbose and not ok:
            print("    text: " + txt[:300].replace("\n", " "))

    n = len(results)
    p = sum(1 for r in results if r["pass"])
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["cat"], [0, 0])
        by_cat[r["cat"]][1] += 1
        by_cat[r["cat"]][0] += 1 if r["pass"] else 0

    print("\n" + "=" * 64)
    print(f"总通过 {p}/{n} = {p / max(1, n) * 100:.1f}%   用时 {time.time() - t0:.0f}s")
    for c, (ok, tot) in sorted(by_cat.items(), key=lambda x: -x[1][1]):
        print(f"  {c:28s} {ok}/{tot}")
    print("=" * 64)

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"model": a.model, "base": a.base, "pass": p, "total": n,
                       "byCat": {c: {"pass": v[0], "total": v[1]} for c, v in by_cat.items()},
                       "detail": results}, f, ensure_ascii=False, indent=2)
        print(f"[ok] 报告 → {a.out}")


if __name__ == "__main__":
    main()
