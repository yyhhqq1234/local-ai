#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_bench.py —— 按 manifest 抓主流能力测试集，归一成统一题面

用法:
  python fetch_bench.py --list
  python fetch_bench.py --set MMLU-Pro --limit 50 --out bench/mmlupro.jsonl
  python fetch_bench.py --set all --limit 50            # 全部抓一遍（每集限 50）
  python fetch_bench.py --set gsm8k --out ... --raw     # 同时保留原始行便于排查字段

归一后的记录:
  {"id","set","type","question","choices":[...],"answer","meta":{...}}
type: mcq / mcq_build / numeric / code / open / rubric
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # kitty-rev 根
MANIFEST = os.path.join(HERE, "eval", "bench", "manifest.json")
DS = "https://datasets-server.huggingface.co"
CJK = re.compile(r"[\u4e00-\u9fa5]")


def curl_json(url, timeout=60):
    r = subprocess.run(["curl", "-sS", "-m", str(timeout), "-H", "User-Agent: kitty-rev/1.0", url],
                       capture_output=True, timeout=timeout + 5)
    if r.returncode != 0:
        raise RuntimeError(f"curl rc={r.returncode} {r.stderr[:120]!r}")
    return json.loads(r.stdout.decode("utf-8", "replace"))


def splits_url(ds):
    return f"{DS}/splits?dataset=" + urllib.parse.quote(ds, safe="/")


def rows_url(ds, cfg, split, off, n):
    return (f"{DS}/rows?dataset=" + urllib.parse.quote(ds, safe="/") +
            f"&config={urllib.parse.quote(cfg, safe='/')}&split={urllib.parse.quote(split, safe='/')}"
            f"&offset={off}&length={n}")


def resolve(ds, prefer_cfg="", prefer_split="train"):
    d = curl_json(splits_url(ds))
    items = (d or {}).get("splits") or []
    if not items:
        return None, None
    if prefer_cfg:
        for it in items:
            if it.get("config") == prefer_cfg and it.get("split") == prefer_split:
                return it["config"], it["split"]
        for it in items:
            if it.get("config") == prefer_cfg:
                return it["config"], it["split"]
    for it in items:
        if it.get("split") == prefer_split:
            return it["config"], it["split"]
    it = items[0]
    return it["config"], it["split"]


def build_choices_mcq(row, mp):
    """标准选择题：choices 是字段名列表（如 A/B/C/D）或直接一个列表值。"""
    ch = mp.get("choices")
    if isinstance(ch, list):
        vals = [row.get(k) for k in ch]
        if all(isinstance(v, str) for v in vals):
            return [v for v in vals if v]
    if isinstance(ch, str) and isinstance(row.get(ch), list):
        return [str(x) for x in row[ch]]
    return []


def normalize(setname, row, mp, typ, rnd):
    if typ == "mcq_build" and "mc1" in mp:
        tgt = row.get(mp["mc1"]) or {}
        labels = (tgt.get("labels") or []) if isinstance(tgt, dict) else []
        texts = (tgt.get("choices") or []) if isinstance(tgt, dict) else []
        if not texts or 0 not in labels:
            return None
        correct = texts[labels.index(1)] if 1 in labels else texts[0]
        wrong = [t for t, l in zip(texts, labels) if l != 1][:3]
        opts = [correct] + wrong
        rnd.shuffle(opts)
        return {"question": row.get(mp.get("question", "question"), ""), "choices": opts,
                "answer": "ABCD"[opts.index(correct)]}
    if typ == "mcq_build" and "correct" in mp:
        correct = row.get(mp["correct"], "")
        wrong = [row.get(k) for k in mp.get("wrong", []) if row.get(k)]
        opts = [correct] + wrong[:3]
        if not correct or len(opts) < 2:
            return None
        rnd.shuffle(opts)
        return {"question": row.get(mp.get("question", "Question"), ""), "choices": opts,
                "answer": "ABCD"[opts.index(correct)]}
    q = row.get(mp.get("question", "question"), "")
    a = row.get(mp.get("answer", "answer"), "")
    if typ in ("numeric", "code", "open") and isinstance(a, str):
        pass
    out = {"question": str(q or ""), "choices": build_choices_mcq(row, mp)}
    if typ == "mcq":
        out["answer"] = str(row.get(mp.get("answer", "answer"), "")).strip().upper()[:1]
    else:
        out["answer"] = a if isinstance(a, str) else json.dumps(a, ensure_ascii=False)[:2000]
    if typ == "code" and mp.get("test"):
        out["test"] = row.get(mp["test"])
    return out


def cmd_list(doc):
    print(f"{'set':18s} {'type':10s} {'limit':>6s} {'prio':5s} hf_id")
    for s in doc["sets"]:
        print(f"{s['name']:18s} {s['type']:10s} {s.get('limit', 0):>6d} {s.get('priority', ''):5s} {s['hf_id']}")


def fetch_one(s, limit, out, raw):
    ds = s["hf_id"]
    if ds.startswith("local:"):
        print(f"[skip] {s['name']}: 本地集，直接跑 eval_kitty.py")
        return 0
    cfg, split = s.get("config"), s.get("split")
    if not cfg or not split:
        cfg2, split2 = resolve(ds, cfg or "", split or "train")
        cfg, split = cfg2 or cfg, split2 or split
    if not cfg:
        print(f"[FATAL] {s['name']}: 解析不到 config/split")
        return 2
    print(f"[{s['name']}] {ds} config={cfg} split={split} limit={limit}")
    rnd = random.Random(13)
    kept, off, bad = 0, 0, 0
    # 先写临时文件，拉取成功才原子替换 —— 原实现直接 open(out,"w")，
    # 拉取失败会把已有的种子数据清成 0 行（2026-10-21 实测踩过）。
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        while kept < limit:
            n = min(100, limit - kept)
            try:
                d = curl_json(rows_url(ds, cfg, split, off, n))
            except Exception as e:
                print(f"  rows 失败 off={off}: {e}")
                break
            rows = (d or {}).get("rows") or []
            if not rows:
                break
            for it in rows:
                row = it.get("row") or {}
                rec = normalize(s["name"], row, s.get("map", {}), s["type"], rnd)
                if not rec:
                    bad += 1
                    continue
                rec.update({"id": f"{s['name']}-{off}-{it.get('row_idx')}", "set": s["name"], "type": s["type"]})
                if raw:
                    rec["raw"] = {k: (v if isinstance(v, (str, int, float, bool, list, dict, type(None))) else str(v))
                                  for k, v in row.items()}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                kept += 1
                if kept >= limit:
                    break
            off += len(rows)
            if len(rows) < n:
                break
    # 原子落盘 + 空结果拒绝覆盖
    if kept == 0:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        print(f"[FATAL] {s['name']}: 拉到 0 行，拒绝覆盖 {out}（原文件保持不变）")
        return 3
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        bak = out + ".bak"
        os.replace(out, bak)
        print(f"[backup] 原文件已备份 → {bak}")
    os.replace(tmp, out)
    print(f"[ok] {s['name']} → {out} kept={kept} bad={bad}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", default="")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--out", default="")
    ap.add_argument("--raw", action="store_true")
    a = ap.parse_args()

    doc = json.load(open(MANIFEST, encoding="utf-8"))
    if a.list:
        cmd_list(doc)
        return 0
    if not a.set:
        ap.print_help()
        return 1

    outdir = os.path.join(HERE, "eval", "bench", "data")
    os.makedirs(outdir, exist_ok=True)
    targets = doc["sets"] if a.set == "all" else [s for s in doc["sets"] if s["name"].lower() == a.set.lower()]
    if not targets:
        print(f"[FATAL] 未知 set: {a.set}（用 --list 看）")
        return 1
    rc = 0
    for s in targets:
        out = a.out or os.path.join(outdir, s["name"].replace(" ", "_") + ".jsonl")
        rc |= fetch_one(s, min(a.limit, s.get("limit", a.limit)), out, a.raw)
    return rc


if __name__ == "__main__":
    sys.exit(main())
