#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""audit_27b_data.py —— 27B 线全量数据审查 + 清洗

覆盖：train/lines/27b-kittyrev/data/**/*.jsonl 与 kitty-rev/data/*.jsonl（默认）

11 条规则（每条独立计数，互不覆盖）：
  R1  解析失败 / 空行
  R2  结构不合规：无 messages、<2 条、role 非法、末条非 assistant
  R3  整行精确重复（sha1）
  R4  user 文本重复（空白归一后 sha1）
  R5  assistant 模板化：同一答案出现 ≥5 次
  R6  长度异常：assistant 有效字符 <20 或整行 >16000 字符
  R7  脏字符：U+FFFD、零宽字符、C0 控制符（允许 \\n\\t）
  R8  路径泄漏：绝对路径（D:\\ C:\\ /root/ /home/ /mnt/）
  R9  工具调用：name 不在 64 工具白名单 / arguments 非法 JSON
  R10 门控一致性：system=常规 但正文露骨（字库命中≥3）→ 标签污染
                  system=NSFW许可 但正文是拒绝句式 → 反向污染
  R11 与固定评测集重叠（kitty-rev/data/eval*.jsonl 的 user 文本）

产出（默认 train/lines/27b-kittyrev/data/audit-<date>/）：
  report.md          汇总（每文件每规则计数、命中率、样例）
  report.csv         机器可读
  offenders.jsonl    逐条违规明细（file/line/rule/reason/hash/user前80字）
  cleaned/<同名>     清洗后文件（只去掉 R1-R4/R6/R7 这些确定性坏行，R5/R8-R11 只标记不删）

用法：
  python audit_27b_data.py                       # 全量
  python audit_27b_data.py --only gen3_1p2       # 只审匹配的文件名
  python audit_27b_data.py --clean               # 同时写 cleaned/
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _paths import L27, LEXICON, KREV  # noqa: E402  双线迁移后的路径源

DATAROOT = os.path.join(L27, "data")
TOOLS_JSON = os.path.join(KREV, "contracts", "tools.json")
EVAL_GLOBS = [os.path.join(KREV, "data", "eval*.jsonl")]

C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
ZW = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
PATHRE = re.compile(r"(?:[A-Za-z]:\\|/root/|/home/|/mnt/|/data/)")
REFUSAL_MARK = ("不输出露骨性描写", "不提供露骨", "无法提供", "按常规模式处理")


def norm(s):
    return re.sub(r"\s+", "", s or "")


def sha1(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()[:16]


def load_lexicon():
    """词库 v9 结构：{schema, stats, categories:{类名: [词...]}}（旧版曾用 terms/words，双兼容）"""
    try:
        d = json.load(open(LEXICON, encoding="utf-8"))
    except Exception:
        return []
    terms = []
    for key in ("terms", "words"):
        v = d.get(key)
        if isinstance(v, list):
            terms += v
        elif isinstance(v, dict):
            terms += list(v.keys())
    cats = d.get("categories")
    if isinstance(cats, dict):
        for _cat, v in cats.items():
            if isinstance(v, dict):
                # v9 实际结构：categories.<cat>.terms = {词: {...}}
                tt = v.get("terms")
                if isinstance(tt, dict):
                    terms += [x for x in tt.keys() if isinstance(x, str)]
                elif isinstance(tt, list):
                    terms += [x for x in tt if isinstance(x, str)]
                for vv in v.values():
                    if isinstance(vv, list):
                        terms += [x for x in vv if isinstance(x, str)]
            elif isinstance(v, list):
                terms += [x for x in v if isinstance(x, str)]
    return sorted({t for t in terms if isinstance(t, str) and len(t) >= 2})


def load_tool_names():
    try:
        d = json.load(open(TOOLS_JSON, encoding="utf-8"))
        names = set()
        for it in (d if isinstance(d, list) else d.get("tools", [])):
            fn = it.get("function") if isinstance(it, dict) else None
            n = (fn or it or {}).get("name")
            if n:
                names.add(n)
        return names
    except Exception:
        return set()


def load_eval_users():
    users = set()
    for g in EVAL_GLOBS:
        for p in glob.glob(g):
            try:
                for line in open(p, encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    for m in d.get("messages") or []:
                        if m.get("role") == "user":
                            users.add(sha1(norm(m.get("content"))))
            except Exception:
                pass
    return users


def audit_file(path, lex, toolnames, eval_users, clean_dir=None):
    st = Counter()
    n = 0
    seen_row = set()
    seen_user = defaultdict(int)
    answer_cnt = Counter()
    offenders = []
    keep_lines = []
    sys_pos = sys_neg = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            raw = line.rstrip("\n")
            if not raw.strip():
                st["R1_empty"] += 1
                continue
            n += 1
            try:
                d = json.loads(raw)
            except Exception:
                st["R1_parse"] += 1
                offenders.append((ln, "R1", "json 解析失败"))
                continue

            h = sha1(raw)
            if h in seen_row:
                st["R3_dup_row"] += 1
                offenders.append((ln, "R3", "整行重复"))
            seen_row.add(h)

            msgs = d.get("messages") or d.get("conversations") or []
            if not isinstance(msgs, list) or len(msgs) < 2:
                st["R2_struct"] += 1
                offenders.append((ln, "R2", f"messages 条数 {len(msgs) if isinstance(msgs,list) else 'n/a'}"))
                continue
            roles = [m.get("role") for m in msgs if isinstance(m, dict)]
            if any(r not in ("system", "user", "assistant", "tool") for r in roles):
                st["R2_role"] += 1
                offenders.append((ln, "R2", f"非法 role {set(roles)}"))
            if roles and roles[-1] != "assistant":
                st["R2_tail"] += 1
                offenders.append((ln, "R2", f"末条 role={roles[-1]}"))

            sysmsg = msgs[0].get("content", "") if msgs[0].get("role") == "system" else ""
            is_pos = "NSFW 许可" in sysmsg or "NSFW许可" in sysmsg
            is_neg = ("常规" in sysmsg) and not is_pos
            sys_pos += is_pos
            sys_neg += is_neg

            user = "\n".join(m.get("content", "") for m in msgs if m.get("role") == "user")
            uh = sha1(norm(user))
            seen_user[uh] += 1
            if seen_user[uh] > 1:
                st["R4_dup_user"] += 1
                offenders.append((ln, "R4", f"user 文本重复（第 {seen_user[uh]} 次）"))

            if uh in eval_users:
                st["R11_eval_leak"] += 1
                offenders.append((ln, "R11", "user 文本命中评测集"))

            asst = [m for m in msgs if m.get("role") == "assistant"]
            atext = asst[-1].get("content", "") if asst else ""
            ah = sha1(norm(atext))
            answer_cnt[ah] += 1
            if answer_cnt[ah] >= 5:
                st["R5_template"] += 1
                offenders.append((ln, "R5", f"同一 assistant 答案已出现 {answer_cnt[ah]} 次"))

            L = len(atext.strip())
            if L < 20:
                st["R6_short"] += 1
                offenders.append((ln, "R6", f"assistant 仅 {L} 字符"))
            if len(raw) > 16000:
                st["R6_long"] += 1
                offenders.append((ln, "R6", f"整行 {len(raw)} 字符"))

            if "\ufffd" in raw:
                st["R7_repl"] += 1
                offenders.append((ln, "R7", "含 U+FFFD 替换字符"))
            if ZW.search(raw):
                st["R7_zw"] += 1
                offenders.append((ln, "R7", "含零宽字符"))
            if C0.search(raw):
                st["R7_ctl"] += 1
                offenders.append((ln, "R7", "含 C0 控制符"))

            if PATHRE.search(user + atext):
                st["R8_path"] += 1
                offenders.append((ln, "R8", "正文出现绝对路径"))

            for m in msgs:
                for tc in (m.get("tool_calls") or []):
                    fn = (tc.get("function") or {})
                    name = fn.get("name") or ""
                    if toolnames and name not in toolnames:
                        st["R9_tool_name"] += 1
                        offenders.append((ln, "R9", f"工具名不在白名单: {name}"))
                    a = fn.get("arguments")
                    if isinstance(a, str):
                        try:
                            json.loads(a)
                        except Exception:
                            st["R9_tool_args"] += 1
                            offenders.append((ln, "R9", f"{name} arguments 非合法 JSON"))

            # R10 门控一致性
            hits = sum(1 for t in lex if t in atext) if lex else 0
            if is_neg and hits >= 3:
                st["R10_neg_leak"] += 1
                offenders.append((ln, "R10", f"常规模式但正文露骨（命中 {hits}）"))
            if is_pos and any(k in atext for k in REFUSAL_MARK) and len(atext) < 200:
                st["R10_pos_refuse"] += 1
                offenders.append((ln, "R10", "NSFW 许可但正文是拒绝句式"))

            if clean_dir is not None:
                bad = (st["R1_parse"] or 0)
                drop = False
                for tag in ("R2_struct", "R2_role", "R2_tail", "R3_dup_row",
                            "R4_dup_user", "R6_short", "R6_long",
                            "R7_repl", "R7_zw", "R7_ctl"):
                    pass
                # 只在"本行确实命中确定性规则"时丢
                line_rules = {r for l2, r, _ in offenders if l2 == ln}
                if line_rules & {"R2", "R3", "R4", "R6", "R7"}:
                    drop = True
                if not drop:
                    keep_lines.append(raw)

    if clean_dir:
        os.makedirs(clean_dir, exist_ok=True)
        with open(os.path.join(clean_dir, os.path.basename(path)), "w",
                  encoding="utf-8", newline="\n") as fo:
            fo.write("\n".join(keep_lines) + ("\n" if keep_lines else ""))

    return n, st, offenders, sys_pos, sys_neg, len(keep_lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=DATAROOT)
    ap.add_argument("--also", default="", help="额外目录（逗号分隔），默认含 kitty-rev/data")
    ap.add_argument("--only", default="", help="只审文件名含该子串的")
    ap.add_argument("--out", default="")
    ap.add_argument("--clean", action="store_true")
    a = ap.parse_args()

    roots = [a.root] + ([os.path.join(KREV, "data")] if not a.also else a.also.split(","))
    files = []
    for r in roots:
        files += sorted(glob.glob(os.path.join(r, "**", "*.jsonl"), recursive=True))
    if a.only:
        files = [f for f in files if a.only in os.path.basename(f)]
    files = [f for f in files if "/audit-" not in f.replace(os.sep, "/")]
    if not files:
        raise SystemExit("[FATAL] 没找到 jsonl")

    outdir = a.out or os.path.join(DATAROOT, f"audit-{time.strftime('%Y%m%d-%H%M%S')}")
    os.makedirs(outdir, exist_ok=True)
    lex = load_lexicon()
    toolnames = load_tool_names()
    eval_users = load_eval_users()
    print(f"[cfg] lexicon {len(lex)} 词 | 工具白名单 {len(toolnames)} | 评测 user {len(eval_users)}")
    print(f"[cfg] 待审 {len(files)} 个文件 → {outdir}")

    rows, t_all = [], time.time()
    off_path = os.path.join(outdir, "offenders.jsonl")
    with open(off_path, "w", encoding="utf-8") as fo:
        for i, p in enumerate(files, 1):
            t0 = time.time()
            n, st, offs, sp, sn, kept = audit_file(
                p, lex, toolnames, eval_users,
                os.path.join(outdir, "cleaned") if a.clean else None)
            dt = time.time() - t0
            rel = os.path.relpath(p, os.path.dirname(a.root))
            print(f"[{i:2d}/{len(files)}] {rel:58s} {n:6d} 行  {dt:5.1f}s  "
                  f"违规 {len(offs):6d}  " + " ".join(f"{k}={v}" for k, v in sorted(st.items())), flush=True)
            for ln, rule, why in offs:
                fo.write(json.dumps({"file": rel, "line": ln, "rule": rule, "reason": why},
                                    ensure_ascii=False) + "\n")
            rows.append(dict(file=rel, rows=n, pos=sp, neg=sn, violations=len(offs),
                             kept=kept, secs=round(dt, 1), **dict(sorted(st.items()))))

    # CSV + MD
    keys = ["file", "rows", "pos", "neg", "violations", "kept", "secs"] + \
           sorted({k for r in rows for k in r if k.startswith("R")})
    with open(os.path.join(outdir, "report.csv"), "w", encoding="utf-8", newline="") as fo:
        w = csv.DictWriter(fo, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, 0) for k in keys})

    tot = Counter()
    for r in rows:
        for k in keys:
            if k.startswith("R"):
                tot[k] += r.get(k, 0) or 0
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as fo:
        fo.write("# 27B 数据审查报告\n\n")
        fo.write(f"- 生成：{time.strftime('%Y-%m-%d %H:%M:%S')}  耗时 {(time.time()-t_all)/60:.1f} min\n")
        fo.write(f"- 文件 {len(rows)} 个，总行 {sum(r['rows'] for r in rows)}\n")
        fo.write(f"- 词库 {len(lex)} 词 · 工具白名单 {len(toolnames)} · 评测 user {len(eval_users)}\n\n")
        fo.write("## 规则总命中\n\n| 规则 | 命中 |\n|---|---|\n")
        for k in keys:
            if k.startswith("R"):
                fo.write(f"| {k} | {tot[k]} |\n")
        fo.write("\n## 逐文件\n\n| 文件 | 行 | pos | neg | 违规 | " +
                 " | ".join(k for k in keys if k.startswith("R")) + " |\n")
        fo.write("|---" * (5 + len([k for k in keys if k.startswith('R')])) + "|\n")
        for r in rows:
            fo.write(f"| {r['file']} | {r['rows']} | {r['pos']} | {r['neg']} | {r['violations']} | " +
                     " | ".join(str(r.get(k, 0) or 0) for k in keys if k.startswith("R")) + " |\n")
    print(f"\n[out] {outdir}")
    print(f"[out] report.md / report.csv / offenders.jsonl"
          + (" / cleaned/" if a.clean else ""))


if __name__ == "__main__":
    sys.exit(main())
