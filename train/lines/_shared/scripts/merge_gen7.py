# -*- coding: utf-8 -*-
"""merge_gen4.py — 拼装 gen4 训练集：工具轨迹 + 重建门控对 + 保留的非门控行

组成
  ① gen6-traj-raw.jsonl   2,400 行（真结构化 tool_calls，60/60 工具覆盖）
  ② gen7-gate.jsonl      10,290 行（创作类正样本已重写：首 token 即正文、禁编排词、pos:neg≈2:1）
  ③ gen3_1p6 的非门控行   约 9.8k（kitty 单步 / general / 其他，原样保留）

判据（拼装后必须打印）
  · tool_calls 行占比 ≥ 8%
  · 门控 pos:neg ≈ 2:1，且 pos 里 0 条含编排词
  · 渲染 0 失败、超 ctx(2048) 0 行
"""
import collections
import hashlib
import json
import os
import sys

V = "train/lines/27b-kittyrev/data/versions"
OUT = os.path.join(V, "gen7-nsfw-kitty.jsonl")
SRC = [os.path.join(V, "gen6-traj-raw.jsonl"), os.path.join(V, "gen7-gate.jsonl"),
       os.path.join(V, "gen7-cont.jsonl")]
P6 = os.path.join(V, "gen3_1p6-nsfw-kitty.jsonl")

ORCH = ("识别到", "先判断", "落点", "拆解", "可执行", "可交付", "同步进度", "常规模式")


def sys_of(row):
    return "".join(m.get("content") or "" for m in (row.get("messages") or [])
                   if m.get("role") == "system")


def main():
    rows = []
    cat = collections.Counter()
    for p in SRC:
        n = 0
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            rows.append(r)
            cat[r["meta"]["cat"]] += 1
            n += 1
        print(f"[in] {os.path.basename(p)}  {n}")

    kept = dropped = 0
    for line in open(P6, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if sys_of(r).startswith("模式："):
            dropped += 1          # 门控行已被 ② 重建替代
            continue
        rows.append(r)
        cat[r["meta"]["cat"]] += 1
        kept += 1
    print(f"[in] gen3_1p6 非门控行 {kept}（跳过门控行 {dropped}）")

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(OUT, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    sha = h.hexdigest()
    open(OUT + ".sha256", "w", encoding="utf-8", newline="\n").write(sha + "\n")

    n = len(rows)
    tc_rows = sum(1 for r in rows if any(m.get("tool_calls") for m in r["messages"]))
    tools_rows = sum(1 for r in rows if r.get("tools"))
    pos = neg = pos_orch = 0
    for r in rows:
        s = sys_of(r)
        if not s.startswith("模式："):
            continue
        a = "".join(m.get("content") or "" for m in r["messages"] if m.get("role") == "assistant")
        if "NSFW" in s:
            pos += 1
            if any(w in a[:200] for w in ORCH):
                pos_orch += 1
        else:
            neg += 1

    print(f"[out] {OUT}  {n} 行  {os.path.getsize(OUT)/(1<<20):.1f} MiB  sha {sha[:16]}")
    print(f"[ratio] tool_calls 行 {tc_rows}/{n} = {tc_rows/n*100:.2f}%   tools 非空 {tools_rows}")
    print(f"[gate]  pos {pos} : neg {neg} = {pos/max(1,neg):.2f}:1   pos 含编排词 {pos_orch}")
    print("[cats] " + ", ".join(f"{k}={v}" for k, v in cat.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
