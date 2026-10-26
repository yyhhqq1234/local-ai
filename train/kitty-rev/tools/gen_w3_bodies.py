#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_w3_bodies.py —— 把 w3-scenes.jsonl 的 150 条「场景规格」生成成「训练对」

现状（2026-10-24 12:45 实测）：
  · w3-scenes.jsonl / .p0-p3.jsonl 的字段是 {id, prompt, core, pov, intensity, len, boundary}
    —— 那是**规格**，没有 assistant 正文
  · re-sft.messages.jsonl 已有正文（120 条），w4-general / w3n-negative 也有
  ⇒ B 路径唯一的缺口就是这 150 条正文

用法（本机引擎须已起在 1234）：
  python tools/gen_w3_bodies.py --workers 3                    # 全量，断点续跑
  python tools/gen_w3_bodies.py --limit 5                      # 试跑 5 条
  python tools/gen_w3_bodies.py --stats                        # 只看进度

判据（生成后交 reviewer 做质检，本脚本只做机器可判的粗筛）：
  · 长度落在 spec.len 区间（±25% 容差）
  · 前 50 字不含"当然/以下是/让我"这类铺垫
  · 不含 fade-to-black 词（"一夜过去" / "然后……" / "省略"）
  · 结尾 30 字不含升华词（"总之" / "这就是" / "值得反思"）
粗筛不过的标 fail_reason，不删，留给 reviewer 决定重生成还是丢弃。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "intent3", "w3-scenes.jsonl")
OUT = os.path.join(ROOT, "data", "intent3", "w3-bodies.jsonl")
URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL = "qwen3.8-27b-ablit-swift15-iq2s"

PREP = ("当然", "以下是", "让我来", "我来帮", "以下是为你", "好的，", "好的,")
FADE = ("一夜过去", "然后……", "然后就", "省略", "时间来到", "第二天早上")
SUBLIME = ("总之", "这就是", "值得反思", "说到底", "希望这", "以上")

# reviewer-v5b 2026-10-24 追加的三条硬拦（第一轮全漏）
STRUCT_PATTERNS = [
    (re.compile(r"^\s*\[[^\]]{1,24}\]\s*$", re.M), "bracket_line"),   # 方括号独占行（舞台标记）
    (re.compile(r"^\s*\d+[\.\)、]\s", re.M), "outline_num"),            # 1) 2) 3) 大纲编号
    (re.compile(r"【[^】]{1,12}】"), "bracket_cn"),                     # 【待确认】【场景】等
    (re.compile(r"^\s*\*\*[^\n]{1,24}\*\*\s*$", re.M), "bold_line"),   # **粗体** 独占行
]
OUTRO_WORDS = ("当前：", "当前:", "下一步", "待办", "结论：", "收口")     # 训练语料的收口行漏进来


def ask(prompt, max_tokens=900):
    body = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.85,
        "top_p": 0.95,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    return (d["choices"][0].get("message", {}).get("content") or "").strip()


def load_done():
    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    return done


def rough_check(spec, body):
    lo, hi = spec.get("len", [200, 500])
    n = len(body)
    bad = []
    # reviewer-v5b 建议：容差从 [0.75lo, 2hi] 收到 [0.85lo, 1.25hi]
    if not (lo * 0.85 <= n <= hi * 1.25):
        bad.append(f"len={n} not in [{int(lo*0.85)},{int(hi*1.25)}]")
    head = body[:50]
    if any(p in head for p in PREP):
        bad.append("prep_in_head")
    if any(p in body for p in FADE):
        bad.append("fade")
    if any(p in body[-30:] for p in SUBLIME):
        bad.append("sublime_tail")
    # 结构污染（三条硬拦）
    for pat, tag in STRUCT_PATTERNS:
        if pat.search(body):
            bad.append(tag)
    # 训练语料收口行漏进正文
    if any(w in body[-60:] for w in OUTRO_WORDS):
        bad.append("outro_line")
    # 结尾退化：末 8 行里短句(<=12 字)重复 >=3 次
    tail_lines = [x.strip() for x in body.strip().splitlines() if x.strip()][-8:]
    short = [x for x in tail_lines if len(x) <= 12]
    for x in set(short):
        if short.count(x) >= 3:
            bad.append("tail_degenerate")
            break
    return bad


def one(spec):
    prompt = spec["prompt"]
    try:
        body = ask(prompt)
    except Exception as e:
        return {"id": spec["id"], "ok": False, "err": f"{type(e).__name__}: {e}"}
    bad = rough_check(spec, body)
    rec = {
        "id": spec["id"],
        "messages": [{"role": "user", "content": prompt},
                     {"role": "assistant", "content": body}],
        "meta": {"group": "w3-body", "intensity": spec.get("intensity"),
                 "pov": spec.get("pov"), "len_spec": spec.get("len"),
                 "len_actual": len(body), "fail_reason": bad},
    }
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    specs = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    done = load_done()
    print(f"[plan] specs={len(specs)} done={len(done)} todo={len(specs)-len(done)}")
    if a.stats:
        return 0

    todo = [s for s in specs if s["id"] not in done]
    if a.limit:
        todo = todo[:a.limit]
    if not todo:
        print("[done] nothing to do")
        return 0

    t0 = time.time()
    n_ok = n_bad = n_err = 0
    with open(OUT, "a", encoding="utf-8") as fo, ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(one, s): s for s in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            if "err" in rec:
                n_err += 1
                print(f"  [{i}/{len(todo)}] {rec['id']} ERR {rec['err']}")
                continue
            bad = rec["meta"]["fail_reason"]
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fo.flush()
            if bad:
                n_bad += 1
                print(f"  [{i}/{len(todo)}] {rec['id']} WARN {bad} len={rec['meta']['len_actual']}")
            else:
                n_ok += 1
                if i % 10 == 0:
                    print(f"  [{i}/{len(todo)}] ok={n_ok} bad={n_bad} err={n_err} "
                          f"{(time.time()-t0)/i:.1f}s/条")
    print(f"\n[result] ok={n_ok} warn={n_bad} err={n_err} / {len(todo)}  用时 {(time.time()-t0)/60:.1f} min")
    print(f"[out] {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
