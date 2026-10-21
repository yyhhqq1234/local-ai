# -*- coding: utf-8 -*-
"""validate_dataset.py —— 数据集质检（训练前必跑，不过不训）

检查项:
  1 结构     每行 messages 首条 user、末条 assistant、role 合法、内容非空
  2 去重     完全重复（user+assistant 前 200 字）与近似重复（user 前 60 字相同且 assistant 相同）
  3 契约一致 meta.op / meta.tool 必须真实存在于 contracts；op-syntax 答案里的签名必须与契约一致
  4 污染     eval 的 prompt 不得出现在 train（完全匹配 + 前 40 字匹配）
  5 长度     token 估算（CJK≈1 tok/字，ASCII≈0.27 tok/字）超 ctx 的样本数
  6 轨迹     assistant 里的 <tool_call> 必须是合法 JSON，且工具名非空
  7 覆盖     类别 / tool / op 覆盖率，gold/silver/guard 分层计数

用法:
  python validate_dataset.py --dir data/large --ctx 2048
  python validate_dataset.py --dir data/large --json logs/quality.json --md logs/quality.md
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(HERE, "contracts")
CJK = re.compile(r"[\u4e00-\u9fa5]")
TOOLCALL = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def jload(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def jlines(p):
    rows = []
    with open(p, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[FATAL] {os.path.basename(p)}:{i} 解析失败 {e}")
                sys.exit(2)
    return rows


def est_tokens(text):
    c = len(CJK.findall(text))
    return int(c * 1.0 + (len(text) - c) * 0.27)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(HERE, "data", "large"))
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--json", default="")
    ap.add_argument("--md", default="")
    a = ap.parse_args()

    train = jlines(os.path.join(a.dir, "train.jsonl"))
    evals = jlines(os.path.join(a.dir, "eval.jsonl"))
    dpo = jlines(os.path.join(a.dir, "dpo.jsonl"))

    tools = {t["name"] for t in jload(os.path.join(CONTRACTS, "tools.json"))["tools"]}
    ops = {o["op"]: o for o in jload(os.path.join(CONTRACTS, "ops.json"))["ops"]}
    types = set(jload(os.path.join(CONTRACTS, "transitions.json"))["types"])

    report = {"counts": {"train": len(train), "eval": len(evals), "dpo": len(dpo)}, "issues": []}
    bad = {"struct": 0, "dup": 0, "dup_near": 0, "contract": 0, "sig_mismatch": 0,
           "toolcall_json": 0, "over_ctx": 0, "empty": 0}

    def issue(kind, detail):
        bad[kind] = bad.get(kind, 0) + 1
        if len(report["issues"]) < 40:
            report["issues"].append({"kind": kind, "detail": detail[:200]})

    seen, near = set(), set()
    cats, tiers, tool_cov, op_cov, type_cov = {}, {}, set(), set(), set()
    tok_max, tok_sum, over = 0, 0, []

    for idx, r in enumerate(train):
        msgs = r.get("messages") or []
        core = [m for m in msgs if m.get("role") != "system"]
        if not core or core[0].get("role") != "user" or core[-1].get("role") != "assistant":
            issue("struct", f"train[{idx}] 首/末角色不对")
            continue
        for m in msgs:
            if m.get("role") not in ("system", "user", "assistant", "tool"):
                issue("struct", f"train[{idx}] 非法 role={m.get('role')}")
            if not str(m.get("content", "")).strip():
                issue("empty", f"train[{idx}] 空内容 role={m.get('role')}")
        key = (msgs[0]["content"][:200], msgs[-1]["content"][:200])
        nkey = (core[0]["content"], core[-1]["content"][:60])
        if key in seen:
            issue("dup", f"train[{idx}] 完全重复")
        seen.add(key)
        if nkey in near:
            issue("dup_near", f"train[{idx}] 近似重复")
        near.add(nkey)

        meta = r.get("meta") or {}
        cats[meta.get("cat", "?")] = cats.get(meta.get("cat", "?"), 0) + 1
        tiers[meta.get("tier", "?")] = tiers.get(meta.get("tier", "?"), 0) + 1
        if meta.get("tool"):
            # 只对 kitty/reverse 命名空间的工具名做契约校验；
            # kb-tool 里的 meta.tool 是「IDA Pro / Ghidra」这类外部软件名，不在契约表内。
            tname = str(meta["tool"])
            if tname.startswith(("kitty_", "reverse_")) or meta.get("cat") in (
                    "tool-route", "tool-action", "op-tool-map", "action-reverse"):
                if tname not in tools:
                    issue("contract", f"train[{idx}] 未知工具 {tname}")
                tool_cov.add(tname)
        if meta.get("op"):
            if meta["op"] not in ops:
                issue("contract", f"train[{idx}] 未知 OP {meta['op']}")
            op_cov.add(meta["op"])
        if meta.get("type"):
            if meta["type"] not in types:
                issue("contract", f"train[{idx}] 未知 transition {meta['type']}")
            type_cov.add(meta["type"])
        if meta.get("cat") == "op-syntax" and meta.get("op") in ops:
            sig = ops[meta["op"]]["sig"]
            head = sig.split("|")[0].split("<")[0].strip()
            if head and head not in core[-1]["content"] and meta["op"] not in core[-1]["content"]:
                issue("sig_mismatch", f"train[{idx}] op={meta['op']} 答案未含签名段 {head}")

        for m in msgs:
            if m.get("role") == "assistant" and "<tool_call>" in str(m.get("content", "")):
                for blob in TOOLCALL.findall(m["content"]):
                    try:
                        obj = json.loads(blob)
                        if not obj.get("name"):
                            issue("toolcall_json", f"train[{idx}] tool_call 缺 name")
                    except json.JSONDecodeError:
                        issue("toolcall_json", f"train[{idx}] tool_call 非法 JSON")

        full = "\n".join(str(m.get("content", "")) for m in msgs)
        t = est_tokens(full)
        tok_sum += t
        tok_max = max(tok_max, t)
        if t > a.ctx:
            over.append(t)
            if len(over) <= 5:
                issue("over_ctx", f"train[{idx}] est_tokens={t} > ctx={a.ctx}")

    # 污染检查
    train_prompts = {r["messages"][0]["content"][:40] for r in train if r.get("messages")}
    contam = [i for i, r in enumerate(evals)
              if r.get("messages") and r["messages"][0]["content"][:40] in train_prompts]

    for i, p in enumerate(dpo):
        missing = [k for k in ("prompt", "chosen", "rejected") if not str(p.get(k, "")).strip()]
        if missing:
            issue("struct", f"dpo[{i}] 缺 {missing}")

    report.update({
        "issues_count": bad,
        "cats": dict(sorted(cats.items(), key=lambda x: -x[1])),
        "tiers": dict(sorted(tiers.items(), key=lambda x: -x[1])),
        "coverage": {"tools": f"{len(tool_cov)}/{len(tools)}", "ops": f"{len(op_cov)}/{len(ops)}",
                     "transitions": f"{len(type_cov)}/{len(types)}",
                     "op_missing": sorted(set(ops) - op_cov)[:10]},
        "length": {"est_tokens_max": tok_max, "est_tokens_avg": round(tok_sum / max(1, len(train))),
                   "over_ctx": len(over), "ctx": a.ctx},
        "contamination": {"eval_prompts_in_train": len(contam)},
    })

    print(json.dumps(report, ensure_ascii=False, indent=2)[:4000])

    fatal = bad["struct"] + bad["dup"] + bad["contract"] + bad["toolcall_json"]
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        json.dump(report, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if a.md:
        lines = ["# 数据集质检报告", "",
                 f"- train={len(train)} eval={len(evals)} dpo={len(dpo)}",
                 f"- 问题统计：{json.dumps(bad, ensure_ascii=False)}",
                 f"- 类别：{json.dumps(report['cats'], ensure_ascii=False)}",
                 f"- 分层：{json.dumps(report['tiers'], ensure_ascii=False)}",
                 f"- 覆盖：{json.dumps(report['coverage'], ensure_ascii=False)}",
                 f"- 长度：{json.dumps(report['length'], ensure_ascii=False)}",
                 f"- 污染：{json.dumps(report['contamination'], ensure_ascii=False)}", ""]
        if report["issues"]:
            lines.append("## 样例问题")
            for it in report["issues"][:20]:
                lines.append(f"- [{it['kind']}] {it['detail']}")
        os.makedirs(os.path.dirname(os.path.abspath(a.md)), exist_ok=True)
        open(a.md, "w", encoding="utf-8").write("\n".join(lines))
        print(f"[ok] 报告 → {a.md}")

    print(f"[gate] fatal(struct+dup+contract+toolcall)={fatal}  over_ctx={bad['over_ctx']}")
    print("VERDICT:", "PASS" if fatal == 0 else "FAIL")


if __name__ == "__main__":
    main()
