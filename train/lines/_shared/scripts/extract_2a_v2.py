#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""extract_2a_v2.py — 从**原始未切分轨迹**重建 2A 数据（解析结构，不切字符窗口）

## 为什么重做（mix-v5 缺陷分析的根）

旧提取器在 47,463 字符（P50）的整段 agent blob 上按字符窗口切尾巴，切点落在句子中间：
    · 41.7% 的训练答案以「## Phase 8: FINAL REVIEW」「4. Observe…」开头
    · 只有 8.1% 严格合格（def/class + 文件路径 + 干净开头）

原始 blob 实测结构：
    【assistant】… ## Phase 1. READING … [CALL execute_bash] {json} … [CALL str_replace_editor] {json} …
    ## Phase 8. FINAL REVIEW … Verification …
    · 代码不在围栏里，而是 str_replace_editor 调用的 JSON 参数（path / file_text / new_str）
    · 收尾是 [CALL finish] {"message": "..."}，整段是 JSON 转义文本

v2 解析结构：
    user      = issue 原文 → 改写为评测形态（真实文件名 + 真实函数名）
    assistant = 收尾总结（去转义、去自述句）+ 真实代码改动（围栏包裹）
    路径来源  优先 summary 里的「Modified File: …」，其次编辑调用的 path；排除草稿/测试脚本

## 用法
  python train/lines/_shared/scripts/extract_2a_v2.py --dry 15     # 抽 15 条看样张
  python train/lines/_shared/scripts/extract_2a_v2.py              # 全量写盘
"""
import argparse
import io
import json
import os
import random
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "data", "agent-traj")
DEFAULT_SRC = [
    os.path.join(SRC_DIR, "nemotron-swe", "swe-16k.jsonl"),
    os.path.join(SRC_DIR, "nemotron-swe", "swe-8k.jsonl"),
    os.path.join(SRC_DIR, "deepswe", "deepswe-8k.jsonl"),
]
DEF_OUT = os.path.join(SRC_DIR, "traj-2a-v2-rawfix.jsonl")

SYS_BASE = (
    "You are a senior software engineer. When you are given a bug report or a code question, you: "
    "1. Identify the root cause precisely, naming the exact file, function and identifier involved. "
    "2. Give the concrete fix: show the code you would change, in a fenced code block. "
    "3. State how to verify the fix. Answer in the same language as the question. "
    "Do not ask for more information; reason from what is given."
)
SYS_NOTOOL = (
    " TOOLS: none. This is a plain text Q&A - you have no filesystem access. "
    "Never emit <tool_call>, <tool_response>, [CALL x], or JSON tool arguments. "
    "Answer directly with root cause + fenced code block."
)

CALL = re.compile(r"\[CALL\s+([a-z_]+)\]")
TESTISH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_|_test[.]|conftest|verification", re.I)
SCRATCH = re.compile(r"(reproduce_issue|repro[.]py|scratch|tmp_|check_|verify_|demo_|[.]ipynb)", re.I)
MODFILE = re.compile(
    r"(?:Modified\s+File|Files?\s+Changed|File|Path)\s*\**\s*[:：]\s*\**\s*`?([^\s`\n]+[.](?:py|js|ts|go|rs|java|cs|c|cpp))`?",
    re.I)
NARR_LEAD = re.compile(
    r"^(I have|I've|I successfully|Successfully|Great|Done|Now|Next|First|Let me|Here)", re.I)


def unescape(t):
    t = t.strip()
    if t.startswith("{"):
        try:
            o = json.loads(t)
            for k in ("message", "thought", "content", "text", "output"):
                if isinstance(o.get(k), str):
                    return o[k]
            return json.dumps(o, ensure_ascii=False)
        except Exception:
            pass
    return (t.replace("\\r\\n", "\n").replace("\\n", "\n")
             .replace('\\"', '"').replace("\\\\", "\\").strip().strip('"').strip("}").strip())


def try_parse_json(raw):
    """从可能夹带散文的负载里抠出第一个完整 JSON 对象（花括号配平 + 字符串感知）。"""
    i = raw.find("{")
    if i < 0:
        return None
    depth, in_str, esc = 0, False, False
    for j in range(i, len(raw)):
        c = raw[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[i:j + 1])
                except Exception:
                    return None
    return None


def split_calls(a):
    parts, last, last_name = [], 0, None
    for m in CALL.finditer(a):
        if last_name is not None:
            parts.append((last_name, a[last:m.start()]))
        last_name, last = m.group(1), m.end()
    if last_name is not None:
        parts.append((last_name, a[last:]))
    return parts


def clean_summary(t, maxlen=1500):
    lines = []
    for ln in t.split("\n"):
        s = ln.rstrip()
        if CALL.search(s) or s.strip().startswith("【"):
            continue
        lines.append(s)
    while lines and not lines[0].strip():
        lines.pop(0)
    out = "\n".join(lines).strip()
    for _ in range(3):
        m = re.match(r"^(I have|I've|I successfully|Successfully)[^.]{0,300}[.]\s*", out)
        if not m:
            break
        out = out[m.end():].strip()
    if len(out) > maxlen:
        out = out[:maxlen].rsplit("\n", 1)[0]
    return out


def best_code_edit(parts, prefer=""):
    """挑最像真实修复的一条编辑：优先命中所挖路径，其次非测试、非草稿、代码更长。"""
    cands = []
    base = os.path.basename(prefer) if prefer else ""
    for name, payload in parts:
        if name not in ("str_replace_editor", "str_replace_based_edit_tool", "editor"):
            continue
        raw = payload.strip()
        o = try_parse_json(raw)
        if not o:
            continue
        path = o.get("path") or o.get("file_path") or ""
        code = o.get("file_text") or o.get("new_str") or ""
        if not isinstance(code, str) or len(code.strip()) < 60:
            continue
        score = 0
        if path and not TESTISH.search(path):
            score += 2
        if path.endswith(".py"):
            score += 1
        if SCRATCH.search(path):
            score -= 3
        if base and path.endswith(base):
            score += 4
        cands.append((score, len(code), path, code.strip()))
    if not cands:
        return "", ""
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return cands[0][2], cands[0][3]


def mine_func(code):
    m = re.search(r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)", code) or \
        re.search(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", code)
    return m.group(1) if m else None


def fence(code):
    if "```" in code:
        return code
    lang = "python"
    if "def " not in code and re.search(r"\b(function|const|let)\b", code):
        lang = "js"
    return "```%s\n%s\n```" % (lang, code)


def build_user(issue, path, func):
    anchor = re.sub(r"\s+", " ", issue).strip()[:260]
    fname = os.path.basename(path) if path else ""
    if fname and func:
        head = "`%s` 里的 `%s()` 出问题了" % (fname, func)
    elif fname:
        head = "`%s` 出问题了" % fname
    elif func:
        head = "`%s()` 出问题了" % func
    else:
        head = "这段代码出问题了"
    return (
        "%s\n\n现象：%s\n\n要求：\n"
        "1. 指名到具体的文件 / 函数 / 标识符\n"
        "2. 直接给出改哪几行，用围栏代码块给出改后代码\n"
        "3. 说明怎么验证\n"
        "4. 不要调用任何工具、不要请求读文件 - 你没有文件系统访问，按已知信息直接作答"
        % (head, anchor)
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", action="append", default=[])
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--dry", type=int, default=0)
    ap.add_argument("--max-ans", type=int, default=900,
                    help="答案字符上限（长上下文削减：默认 900，超过则保留总结头部并裁剪代码）")
    ap.add_argument("--strict-path", type=int, default=1,
                    help="1=只保留「summary 里的 Modified File 与代码改动路径一致」的行（质量优先）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    srcs = args.src or DEFAULT_SRC

    kept = []
    rej = {"nosum": 0, "nocode": 0, "scratch": 0}
    n_seen = 0
    for p in srcs:
        if not os.path.isfile(p):
            print("[skip] 缺 %s" % p)
            continue
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            n_seen += 1
            msgs = o.get("messages") or []
            issue = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
            blob = next((m.get("content") or "" for m in msgs if m.get("role") == "assistant"), "")
            if not issue or not blob:
                continue

            parts = split_calls(blob)
            summary = ""
            for want in ("finish", "think", "message"):
                for nm, pl in reversed(parts):
                    if nm == want:
                        cand = clean_summary(unescape(pl))
                        if len(cand) >= 200:
                            summary = cand
                            break
                if summary:
                    break
            if not summary:
                summary = clean_summary(unescape(blob[-1400:]))
            if len(summary) < 200:
                rej["nosum"] += 1
                continue

            mf = MODFILE.search(summary)
            prefer = mf.group(1) if mf else ""
            path, code = best_code_edit(parts, prefer)
            if not path and prefer:
                path = prefer
            if len(code) < 60:
                rej["nocode"] += 1
                continue
            if SCRATCH.search(path or ""):
                rej["scratch"] += 1
                continue
            if TESTISH.search(path or ""):
                rej["test"] = rej.get("test", 0) + 1
                continue
            # 严格模式：只收「总结里点名的文件」与「代码改动文件」一致的行，
            # 否则 user 里写 A 文件、答案给 B 文件代码，等于教模型答非所问。
            if args.strict_path and prefer and not (path or "").endswith(os.path.basename(prefer)):
                rej["mismatch"] = rej.get("mismatch", 0) + 1
                continue
            if args.strict_path and not prefer:
                rej["nofile"] = rej.get("nofile", 0) + 1
                continue

            func = mine_func(code)
            # 长上下文削减：先压代码行数，再压总结，整体不超 --max-ans
            budget_code = max(200, int(args.max_ans * 0.55))
            lines_out, used = [], 0
            for ln in code.split("\n"):
                if used + len(ln) + 1 > budget_code:
                    lines_out.append("# ... (truncated)")
                    break
                lines_out.append(ln)
                used += len(ln) + 1
            code_t = "\n".join(lines_out)
            assistant = summary[: max(200, args.max_ans - used - 40)].rstrip() + "\n\n" + fence(code_t)
            if len(assistant) > args.max_ans:
                assistant = assistant[:args.max_ans].rsplit("\n", 1)[0]

            kept.append({
                "messages": [
                    {"role": "system", "content": SYS_BASE + SYS_NOTOOL},
                    {"role": "user", "content": build_user(issue, path, func)},
                    {"role": "assistant", "content": assistant},
                ],
                "meta": {"domain": "swe_rawfix", "src": os.path.basename(p),
                         "path": path, "func": func,
                         "repo": (o.get("meta") or {}).get("repo", "")},
            })
            if args.dry and len(kept) >= args.dry:
                break
        if args.dry and len(kept) >= args.dry:
            break

    random.Random(args.seed).shuffle(kept)
    if args.n:
        kept = kept[:args.n]

    if args.dry:
        for i, r in enumerate(kept[:4]):
            print("=" * 78)
            print("[%d] user   : %s" % (i, r["messages"][1]["content"][:180].replace("\n", " ")))
            print("    answer : %s" % r["messages"][2]["content"][:260].replace("\n", " "))
            print("    meta   : path=%s func=%s" % (r["meta"]["path"], r["meta"]["func"]))
        print("=" * 78)
        print("seen %d -> kept %d - 剔除 %s" % (n_seen, len(kept), rej))
        return

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as fo:
        for o in kept:
            fo.write(json.dumps(o, ensure_ascii=False) + "\n")

    code_ok = sum(1 for r in kept if "```" in r["messages"][2]["content"])
    withfile = sum(1 for r in kept if r["meta"]["path"])
    withfunc = sum(1 for r in kept if r["meta"]["func"])
    nar = sum(1 for r in kept if NARR_LEAD.match(r["messages"][2]["content"][:60].strip()))
    tc = sum(1 for r in kept if "[CALL " in r["messages"][2]["content"]
             or "<tool_call>" in r["messages"][2]["content"])
    chars = sum(len(r["messages"][2]["content"]) for r in kept)
    print("seen %d -> kept %d (剔除 %s)" % (n_seen, len(kept), rej))
    print("  代码围栏 %d/%d - 真实路径 %d - 函数名 %d - 自述开头 %d - 工具标记 %d"
          % (code_ok, len(kept), withfile, withfunc, nar, tc))
    print("  assistant 字符 %d (均值 %d)" % (chars, chars // max(len(kept), 1)))
    print("  -> %s" % args.out)


if __name__ == "__main__":
    main()
