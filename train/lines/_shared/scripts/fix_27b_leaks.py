#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_27b_leaks.py —— 处理审查里的两类泄漏：评测污染(R11) + 本机/远端绝对路径(R8)

R11 评测污染
  做法：以 kitty-rev/data/eval*.jsonl 的 user 文本（空白归一 + sha1）为黑名单，
        训练文件里命中即整行剔除；eval*.jsonl 自身不参与（自匹配无意义）。
  判据：剔除后训练集中与评测集的 user 交集必须为 0。

R8 路径泄漏
  只替换「我们自己的环境路径」，把模型该学的目标路径（C:\\Windows、D:\\Games 等）保留：
      D:\\BaiduNetdiskDownload\\Local-AI  →  <WORKSPACE>
      /root/autodl-tmp                    →  <REMOTE_TMP>
      /root/miniconda3                    →  <REMOTE_ENV>
      /root/autodl-pub                    →  <REMOTE_PUB>
    替换作用于 messages[].content 与 tool_calls[].function.arguments（字符串形态时）。
  判据：替换后 <WORKSPACE>/<REMOTE_*> 计数 > 0，且上述四个原始前缀计数 = 0。

用法：
  python fix_27b_leaks.py --src .../gen3_1p3-nsfw-kitty.jsonl --out .../gen3_1p4-nsfw-kitty.jsonl
  python fix_27b_leaks.py --src ... --out ... --dry     # 只统计不写
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _paths import KREV  # noqa: E402

WS = re.compile(r"[A-Za-z]:[\\/]+BaiduNetdiskDownload[\\/]+Local-AI", re.I)
REMOTE = {
    re.compile(r"/root/autodl-tmp", re.I): "<REMOTE_TMP>",
    re.compile(r"/root/miniconda3", re.I): "<REMOTE_ENV>",
    re.compile(r"/root/autodl-pub", re.I): "<REMOTE_PUB>",
}
GEN_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"',，。；]{2,90}")   # 仅用于统计其它盘符路径
EVAL_GLOBS = [os.path.join(KREV, "data", "eval*.jsonl")]


def nk(s):
    return hashlib.sha1(re.sub(r"\s+", "", s or "").encode("utf-8", "replace")).hexdigest()


def load_eval_users():
    users, files = set(), []
    for g in EVAL_GLOBS:
        for p in glob.glob(g):
            files.append(os.path.basename(p))
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                for m in d.get("messages") or []:
                    if m.get("role") == "user":
                        users.add(nk(m.get("content")))
    return users, files


def scrub(s, cnt):
    if not isinstance(s, str):
        return s
    if WS.search(s):
        cnt["R8_workspace"] += 1
        s = WS.sub("<WORKSPACE>", s)
    for rx, rep in REMOTE.items():
        if rx.search(s):
            cnt["R8_" + rep.strip("<>").lower()] += 1
            s = rx.sub(rep, s)
    for m in GEN_PATH.findall(s):
        cnt["R8_other_kept"] += 1
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    ev_users, ev_files = load_eval_users()
    print(f"[eval] 黑名单来源 {len(ev_files)} 个文件，user 去重 {len(ev_users)}")

    stat = Counter()
    kept = []
    touched = 0
    for line in open(a.src, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        stat["in"] += 1
        msgs = d.get("messages") or []
        users = [m.get("content") or "" for m in msgs if m.get("role") == "user"]
        if any(nk(u) in ev_users for u in users):
            stat["R11_dropped"] += 1
            continue
        cnt = Counter()
        for m in msgs:
            if "content" in m:
                m["content"] = scrub(m["content"], cnt)
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                if isinstance(fn.get("arguments"), str):
                    fn["arguments"] = scrub(fn["arguments"], cnt)
        for k, v in cnt.items():
            stat[k] += v
        if any(v for k, v in cnt.items() if k != "R8_other_kept"):
            touched += 1
        kept.append(d)
        stat["out"] += 1

    print(f"[统计] 输入 {stat['in']}  剔除 R11 {stat['R11_dropped']}  输出 {stat['out']}")
    print(f"[R8] 命中并替换：<WORKSPACE> {stat['R8_workspace']} · "
          f"<REMOTE_TMP> {stat['R8_remote_tmp']} · <REMOTE_ENV> {stat['R8_remote_env']} · "
          f"<REMOTE_PUB> {stat['R8_remote_pub']}")
    print(f"[R8] 保留的其它盘符路径（正常目标路径，不动）：{stat['R8_other_kept']} 处")
    print(f"[R8] 受影响行 {touched}")

    if a.dry:
        print("[dry] 不写文件")
        return 0

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as fo:
        for r in kept:
            fo.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
    open(a.out + ".sha256", "w").write(h + "\n")
    size = os.path.getsize(a.out)

    # 复核：输出集里不应再有原始前缀 / 评测交集
    bad_ws = bad_rm = 0
    out_users = set()
    for line in open(a.out, encoding="utf-8"):
        d = json.loads(line)
        blob = json.dumps(d, ensure_ascii=False)
        bad_ws += len(WS.findall(blob))
        bad_rm += sum(len(rx.findall(blob)) for rx in REMOTE)
        for m in d.get("messages") or []:
            if m.get("role") == "user":
                out_users.add(nk(m.get("content")))
    print(f"[复核] 原始前缀残留 本地{bad_ws} 远端{bad_rm}（应全为 0）")
    print(f"[复核] 与评测集 user 交集 {len(out_users & ev_users)}（应为 0）")
    print(f"[out] {a.out}  {len(kept)} 行  {size/1048576:.1f} MiB  sha {h[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
