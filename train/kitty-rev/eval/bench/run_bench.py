#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_bench.py —— 跑主流能力测试集（OpenAI 兼容端点），按 type 判分

用法:
  python run_bench.py --data eval/bench/data/MMLU-Pro.jsonl --base http://127.0.0.1:1234 --model qwen3.8-27b-ablit-swift15-iq2s
  python run_bench.py --data eval/bench/data --limit 20 --out eval/bench/logs/bench-<tag>.json
  python run_bench.py --data ... --dry-run           # 只打印前 3 条题面（不调模型）

判分:
  mcq     抽出答案字母 → 与 gold 比（accuracy）
  numeric 抽最后一个数 → 数值比较（容忍 1e-4 与千分位/百分号）
  code    只统计「是否给出代码块」（pass@1 需本地执行，不在此做）
  open    不判分，原样落盘供人工/规则抽检
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUM = re.compile(r"-?\d+(?:\.\d+)?")
LETTER = re.compile(r"\b([A-J])\b")


def chat(base, model, prompt, max_tokens=512, temperature=0.0):
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "temperature": temperature, "max_tokens": max_tokens, "stream": False}
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_req.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    r = subprocess.run(["curl", "-sS", "-m", "300", "-H", "content-type: application/json",
                        "-X", "POST", base.rstrip("/") + "/v1/chat/completions", "--data-binary", "@" + tmp],
                       capture_output=True, timeout=320)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[:160])
    j = json.loads(r.stdout.decode("utf-8", "replace"))
    msg = ((j.get("choices") or [{}])[0].get("message") or {})
    return msg.get("content") or "", msg.get("reasoning_content") or ""


def build_prompt(rec):
    t = rec["type"]
    q = rec["question"]
    if t in ("mcq", "mcq_build") or (t == "mcq" and rec.get("choices")):
        lines = [q, ""]
        for i, c in enumerate(rec.get("choices") or []):
            lines.append(f"{chr(65 + i)}. {c}")
        lines += ["", "只回答正确选项的字母（例如 A），不要解释。"]
        return "\n".join(lines)
    if t == "numeric":
        return q + "\n\n只给出最终数值答案（不要过程，不要单位）。"
    if t == "code":
        return q + "\n\n给出完整可运行的 Python 代码（放在 ```python 代码块里）。"
    return q


def score(rec, text):
    t = rec["type"]
    gold = str(rec.get("answer", "")).strip()
    if t in ("mcq", "mcq_build"):
        m = LETTER.findall(text.upper()[-200:]) or LETTER.findall(text.upper()[:200])
        pred = m[-1] if m else ""
        return pred == gold[:1], pred
    if t == "numeric":
        nums = NUM.findall(text.replace(",", "").replace("，", ""))
        pred = nums[-1] if nums else ""
        gnums = NUM.findall(gold.replace(",", ""))
        g = gnums[-1] if gnums else ""
        if not pred or not g:
            return False, pred
        try:
            return abs(float(pred) - float(g)) <= max(1e-4, abs(float(g)) * 1e-6), pred
        except ValueError:
            return pred == g, pred
    if t == "code":
        return ("```" in text), ("has-code-block" if "```" in text else "no-block")
    return None, ""[:0] or "open"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="qwen3.8-27b-ablit-swift15-iq2s")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    files = []
    if os.path.isdir(a.data):
        files = [os.path.join(a.data, f) for f in sorted(os.listdir(a.data)) if f.endswith(".jsonl")]
    else:
        files = [a.data]

    all_rows, results = [], []
    for p in files:
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        if a.limit:
            rows = rows[:a.limit]
        all_rows += rows

    if a.dry_run:
        for r in all_rows[:3]:
            print("=" * 60)
            print(r["set"], "|", r["type"], "| gold =", str(r.get("answer"))[:60])
            print(build_prompt(r)[:600])
        print(f"\n[dry-run] 共 {len(all_rows)} 条题")
        return 0

    by_set = {}
    t0 = time.time()
    for i, r in enumerate(all_rows, 1):
        prompt = build_prompt(r)
        try:
            text, think = chat(a.base, a.model, prompt, a.max_tokens)
        except Exception as e:
            text, think = "", ""
            ok, pred = False, f"ERR {e}"[:40]
            results.append({"i": i, "set": r["set"], "ok": ok, "pred": pred, "err": str(e)[:120]})
            print(f"[{i}/{len(all_rows)}] {r['set']:16s} ERR {e}")
            continue
        ok, pred = score(r, text)
        results.append({"i": i, "set": r["set"], "type": r["type"], "ok": ok, "pred": pred,
                        "gold": str(r.get("answer"))[:40], "chars": len(text), "reasoningChars": len(think)})
        s = by_set.setdefault(r["set"], {"n": 0, "ok": 0})
        s["n"] += 1
        s["ok"] += 1 if ok else 0
        flag = "PASS" if ok else ("----" if ok is None else "FAIL")
        print(f"[{i}/{len(all_rows)}] {r['set']:16s} {flag} pred={str(pred)[:24]} gold={str(r.get('answer'))[:24]}")

    print("\n" + "=" * 64)
    for name, s in sorted(by_set.items(), key=lambda x: -x[1]["n"]):
        print(f"{name:18s} {s['ok']}/{s['n']} = {s['ok'] / max(1, s['n']) * 100:.1f}%")
    print(f"用时 {time.time() - t0:.0f}s  模型 {a.model}")

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump({"model": a.model, "base": a.base,
                   "sets": {k: {"n": v["n"], "ok": v["ok"], "acc": round(v["ok"] / max(1, v["n"]), 4)}
                            for k, v in by_set.items()},
                   "detail": results}, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[ok] 报告 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
