#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_bench_mirror.py —— datasets-server 不可达时的等价取数路径

fetch_bench.py 硬编码 https://datasets-server.huggingface.co（本机 curl rc=28 超时），
本脚本改走 hf-mirror 的 parquet 直链，产出与 fetch_bench.py 相同的行 schema：
  {"id","set","type","question","choices":[...],"answer","meta":{...}}

用法（远端）:
  python fetch_bench_mirror.py --out kitty-rev/eval/bench/data [--limit-scale 1.0]

目标量：MMLU-Pro 200 / GSM8K 200 / GPQA-Diamond 100。
GPQA 是 gated 数据集，无 token 会 401 → 自动跳过并记 skipped（不伪造）。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

MIRROR = "https://hf-mirror.com/datasets"

SETS = [
    {
        "set": "MMLU-Pro",
        "url": f"{MIRROR}/TIGER-Lab/MMLU-Pro/resolve/main/data/test-00000-of-00001.parquet",
        "limit": 200,
        "kind": "mcq_options",
    },
    {
        "set": "GSM8K",
        "url": f"{MIRROR}/openai/gsm8k/resolve/main/main/test-00000-of-00001.parquet",
        "limit": 200,
        "kind": "gsm8k",
    },
    {
        "set": "GPQA-Diamond",
        "url": f"{MIRROR}/Idavidrein/gpqa/resolve/main/gpqa_diamond/train-00000-of-00001.parquet",
        "limit": 100,
        "kind": "gpqa",
    },
]


def curl(url, dst, timeout=180):
    r = subprocess.run(
        ["curl", "-sSL", "--max-time", str(timeout), "-o", dst, url],
        capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
        raise RuntimeError(f"curl rc={r.returncode} size="
                           f"{os.path.getsize(dst) if os.path.exists(dst) else 0} {r.stderr[:120]!r}")
    return os.path.getsize(dst)


def build_mmlu_pro(row, idx):
    # 注意: pandas parquet 的 options 是 numpy array，`x or []` 会抛
    # "truth value of an array is ambiguous" —— 必须显式 list() 后再判空
    raw = row.get("options")
    try:
        opts = [str(o) for o in list(raw)]
    except TypeError:
        opts = []
    ans = str(row.get("answer") or "").strip().upper()[:1]
    if not opts or ans not in list("ABCDEFGHIJ"):
        return None
    return {
        "id": f"mmlu-pro-{idx}",
        "set": "MMLU-Pro",
        "type": "mcq",
        "question": str(row.get("question") or ""),
        "choices": [str(o) for o in opts],
        "answer": ans,
        "meta": {"cat": str(row.get("category") or "unknown"),
                 "src": str(row.get("src") or "")},
    }


def build_gsm8k(row, idx):
    q = str(row.get("question") or "")
    a = str(row.get("answer") or "")
    gold = a.split("####")[-1].strip() if "####" in a else ""
    gold = gold.replace(",", "")
    if not q or not gold:
        return None
    return {
        "id": f"gsm8k-{idx}",
        "set": "GSM8K",
        "type": "numeric",
        "question": q,
        "choices": [],
        "answer": gold,
        "meta": {"cat": "math-word", "solution": a[:400]},
    }


def build_gpqa(row, idx):
    q = str(row.get("Question") or row.get("question") or "")
    correct = str(row.get("Correct Answer") or row.get("correct_answer") or "")
    wrongs = [str(row.get(k) or "") for k in (
        "Incorrect Answer 1", "Incorrect Answer 2", "Incorrect Answer 3",
        "incorrect_answer_1", "incorrect_answer_2", "incorrect_answer_3")]
    wrongs = [w for w in wrongs if w]
    if not q or not correct or len(wrongs) < 3:
        return None
    opts = [correct] + wrongs[:3]
    # 固定顺序：gold 恒在 A 位太重，改为按 (idx % 4) 轮转，答案随之移动
    shift = idx % 4
    opts = opts[shift:] + opts[:shift]
    letter = "ABCD"[opts.index(correct)]
    return {
        "id": f"gpqa-d-{idx}",
        "set": "GPQA-Diamond",
        "type": "mcq",
        "question": q,
        "choices": opts,
        "answer": letter,
        "meta": {"cat": str(row.get("Subdomain") or row.get("subdomain") or "unknown")},
    }


BUILDERS = {"mcq_options": build_mmlu_pro, "gsm8k": build_gsm8k, "gpqa": build_gpqa}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="kitty-rev/eval/bench/data")
    ap.add_argument("--limit-scale", type=float, default=1.0)
    ap.add_argument("--only", default="")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    report = []
    for spec in SETS:
        name = spec["set"]
        if a.only and a.only != name:
            continue
        limit = max(1, int(spec["limit"] * a.limit_scale))
        dst = os.path.join(a.out, name + ".jsonl")
        tmp = os.path.join(tempfile.gettempdir(), name.replace("/", "_") + ".parquet")
        try:
            size = curl(spec["url"], tmp)
        except Exception as e:
            print(f"[skip] {name}: parquet 不可达 {e}")
            report.append({"set": name, "rows": 0, "status": f"skip:{e}"[:120]})
            continue
        try:
            import pandas as pd
            df = pd.read_parquet(tmp)
        except Exception as e:
            print(f"[skip] {name}: parquet 解析失败 {e}")
            report.append({"set": name, "rows": 0, "status": f"parse:{e}"[:120]})
            continue

        builder = BUILDERS[spec["kind"]]
        rows, bad = [], 0
        for i, rec in enumerate(df.to_dict("records")):
            if len(rows) >= limit:
                break
            try:
                r = builder(rec, i)
            except Exception:
                r = None
            if r is None:
                bad += 1
                continue
            rows.append(r)

        if not rows:
            print(f"[skip] {name}: 解析出 0 行（bad={bad}），不覆盖既有文件")
            report.append({"set": name, "rows": 0, "status": f"empty bad={bad}"})
            continue

        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            bak = dst + ".seed.bak"
            if not os.path.exists(bak):
                os.replace(dst, bak)
                print(f"[bak ] {dst} -> {bak}")

        with open(dst, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"[ok  ] {name}: {len(rows)} 行 (bad={bad}, parquet {size/2**20:.1f} MiB) -> {dst}")
        report.append({"set": name, "rows": len(rows), "status": "ok", "bad": bad})

    print("---REPORT---")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
