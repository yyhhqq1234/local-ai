#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""9B 数据全量体检：逐文件统计污染面与规模，输出可判读的表格。

检查项（每项都对应一次真实踩坑）：
  role_mark   【assistant】/【user】 等角色标记（B11）
  tool_call   原始 <tool_call> 块数 + 名字是否在 catalog / harness 白名单
  call_style  [CALL xxx] OpenHands 风格调用
  stdio_noise [Command finished…] / [Python interpreter…] / [Current working directory…]
  code_pct    含 ``` 的行占比
  dup_pct     user 文本重复率（同文件内）
  len         正文长度 p50 / p90 / max
用法：
  python audit_9b_data.py            # 只报告
  python audit_9b_data.py --json out.json
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
BASE = "train/lines/9b-oxcoder/data"
CATALOG = os.path.join(BASE, "kitty-tool-catalog.json")
HARNESS = {"read", "write", "edit", "glob", "grep", "pwsh", "ops_bash", "job_output",
           "job_kill", "list_agents", "send_message", "todo_write", "skill", "webfetch",
           "web_search", "evaluate_script", "click_element", "take_screenshot"}

ROLE = re.compile(r"【(assistant|user|system|observation)】")
TC = re.compile(r"<tool_call>", re.S)
TCNAME = re.compile(r"<tool_call>\s*\{.*?\"name\"\s*:\s*\"([^\"]+)\"", re.S)
CALL = re.compile(r"\[CALL\s+([a-z_]+)\]")
NOISE = re.compile(r"\[(Command finished|The command completed|Python interpreter|Current working directory)[^\]]*\]", re.I)


def asst(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "assistant")


def user(o):
    return "".join(m.get("content") or "" for m in o.get("messages", []) if m.get("role") == "user")


def pct(x, n):
    return f"{100.0*x/n:.1f}%" if n else "-"


def audit(path, cat_names):
    rows = 0
    rm = tc = call = noise = code = 0
    names, users = {}, set()
    L = []
    for line in io.open(path, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        rows += 1
        a, u = asst(o), user(o)
        L.append(len(a))
        if ROLE.search(a) or ROLE.search(u):
            rm += 1
        if TC.search(a):
            tc += 1
            for nm in TCNAME.findall(a):
                names[nm] = names.get(nm, 0) + 1
        for nm in CALL.findall(a):
            call += 1
            names[nm] = names.get(nm, 0) + 1
        if NOISE.search(a):
            noise += 1
        if "```" in a:
            code += 1
        k = hashlib.md5(u[:300].encode("utf-8", "ignore")).hexdigest()
        users.add(k)
    L.sort()
    out = {
        "file": os.path.relpath(path, ".").replace("\\", "/"),
        "rows": rows,
        "role_mark": rm, "tool_call": tc, "call_style": call, "stdio_noise": noise,
        "code_pct": round(100.0 * code / rows, 1) if rows else 0,
        "dup_pct": round(100.0 * (1 - len(users) / rows), 1) if rows else 0,
        "len_p50": L[len(L) // 2] if L else 0,
        "len_p90": L[int(len(L) * 0.9)] if L else 0,
        "len_max": L[-1] if L else 0,
        "names": names,
    }
    bad = {n: c for n, c in names.items()
           if not n.startswith("kitty_") and n not in HARNESS
           and (cat_names is None or n not in cat_names)}
    out["suspect"] = bad
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    ap.add_argument("--max-files", type=int, default=0)
    a = ap.parse_args()

    cat_names = set()
    if os.path.exists(CATALOG):
        c = json.load(io.open(CATALOG, encoding="utf-8"))
        cat_names = set(c.keys()) if isinstance(c, dict) else {t.get("name") for t in c}

    files = []
    for dp, _, fns in os.walk(BASE):
        for fn in fns:
            if fn.endswith(".jsonl") and ".bak" not in fn:
                files.append(os.path.join(dp, fn))
    files.sort()
    if a.max_files:
        files = files[: a.max_files]

    results = []
    print(f"{'文件':52} {'行数':>7} {'角色':>5} {'tcall':>6} {'CALL':>5} {'日志':>5} {'代码%':>6} {'重复%':>6} {'p50':>6}")
    print("-" * 108)
    for p in files:
        r = audit(p, cat_names)
        results.append(r)
        print(f"{r['file'][-52:]:52} {r['rows']:>7} {r['role_mark']:>5} {r['tool_call']:>6} "
              f"{r['call_style']:>5} {r['stdio_noise']:>5} {r['code_pct']:>6} {r['dup_pct']:>6} {r['len_p50']:>6}")
        if r["suspect"]:
            top = ", ".join(f"{k}×{v}" for k, v in sorted(r["suspect"].items(), key=lambda x: -x[1])[:6])
            print(f"{'':52} ⚠ 目录外名: {top}")
    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"\n报告 → {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
