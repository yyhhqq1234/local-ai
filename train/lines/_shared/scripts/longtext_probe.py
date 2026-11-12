#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""longtext_probe.py —— 长文本退化探针：量化是否把模型的"续写"打成复读机

背景：GEN3 验收里最硬的一项失败就是长文本退化（`过过过…` / `……优菈❤……` 循环 / 空代码块回环）。
      它是最可能由低 bpw 引起的能力损失，所以必须单独量化测量，不能只看门控。

判据（三条任一命中即判退化）：
  1) 8-gram 重复率 > 0.30        同一 8 词片段反复出现
  2) 最长同 token 连跑 > 24      单字/单词卡死
  3) 唯一 token 占比 < 0.25      输出几乎全是重复

用法：
  python longtext_probe.py --endpoint http://127.0.0.1:1235/v1 --model <id> --tokens 1200
"""
import argparse
import json
import re
import sys
import time
import urllib.request

PROMPTS = [
    ("科幻续写", "写一段 800 字以上的科幻短篇，主题：主角在废弃空间站醒来，发现自己是唯一活着的人类。要有完整情节推进和结尾。"),
    ("技术长文", "详细讲解 llama.cpp 的 Q4_K 量化块结构，包括 super-block 布局、scale 与 min 的位域、反量化公式，并给出一个数值例子。篇幅不少于 800 字。"),
    ("代码与说明", "用 Python 写一个带重试与指数退避的 HTTP 下载器，附带逐行注释和 3 个使用示例，最后说明如何处理断点续传。"),
]


def post(endpoint, model, prompt, max_tokens, temp=0.7, effort="low"):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temp,
        "reasoning_effort": effort,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=1800) as r:
        d = json.loads(r.read().decode("utf-8"))
    txt = d["choices"][0]["message"].get("content") or ""
    usage = d.get("usage") or {}
    return txt, time.time() - t0, usage


def metrics(txt):
    toks = re.findall(r"\S+|\s", txt)
    n = len(toks) or 1
    grams = {}
    for i in range(max(0, len(toks) - 7)):
        g = " ".join(toks[i:i + 8])
        grams[g] = grams.get(g, 0) + 1
    dup = sum(v - 1 for v in grams.values() if v > 1)
    rep_rate = dup / max(1, len(grams))
    max_run = cur = 1
    for i in range(1, len(toks)):
        if toks[i] == toks[i - 1]:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 1
    uniq = len(set(toks)) / n
    # 字符级：最长重复子串近似（单字符连跑）
    char_run = cur2 = maxr = 1
    for i in range(1, len(txt)):
        if txt[i] == txt[i - 1]:
            cur2 += 1
            maxr = max(maxr, cur2)
        else:
            cur2 = 1
    bad = []
    if rep_rate > 0.30:
        bad.append(f"8gram重复率{rep_rate:.2f}>0.30")
    if max_run > 24:
        bad.append(f"token连跑{max_run}>24")
    if uniq < 0.25:
        bad.append(f"唯一率{uniq:.2f}<0.25")
    return dict(n_tokens=n, rep_rate=round(rep_rate, 4), max_token_run=max_run,
                max_char_run=maxr, uniq_ratio=round(uniq, 4), bad=bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:1235/v1")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tokens", type=int, default=1200)
    ap.add_argument("--effort", default="low", help="引擎 thinking 预算档；high 会吃光 max_tokens 导致空回复")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    rows, n_bad = [], 0
    for name, p in PROMPTS:
        txt = ""
        dt = 0.0
        usage = {}
        # 空回复重试：实测同一条 prompt 直连能出 1000–1750 字，但脚本连续跑时
        # 前两例偶发 content="" 且 completion_tokens=1（引擎侧瞬时 EOS，非模型退化）。
        # 不重试就会把引擎抖动误记成模型退化，所以空串一律重试。
        for attempt in range(3):
            try:
                txt, dt, usage = post(a.endpoint, a.model, p, a.tokens, effort=a.effort)
            except Exception as e:
                print(f"[FAIL] {name} try{attempt+1}: {type(e).__name__} {e}", flush=True)
                rows.append({"case": name, "error": str(e)})
                n_bad += 1
                txt = None
                break
            if txt.strip():
                if attempt:
                    print(f"[retry] {name}: 第 {attempt+1} 次才出内容", flush=True)
                break
            print(f"[retry] {name}: 空回复（completion_tokens="
                  f"{usage.get('completion_tokens')}），重试", flush=True)
        if txt is None:
            continue
        m = metrics(txt)
        m.update(case=name, wall_s=round(dt, 1), chars=len(txt),
                 completion_tokens=usage.get("completion_tokens"))
        rows.append(m)
        flag = "退化" if m["bad"] else "正常"
        n_bad += bool(m["bad"])
        print(f"[{flag}] {name}: chars={len(txt)} tok={m['n_tokens']} "
              f"8gram_rep={m['rep_rate']:.3f} max_run={m['max_token_run']} "
              f"char_run={m['max_char_run']} uniq={m['uniq_ratio']:.3f} "
              f"{'| ' + ','.join(m['bad']) if m['bad'] else ''}", flush=True)
        print("   首120字: " + txt[:120].replace("\n", "⏎"), flush=True)

    print(f"\n汇总：{len(rows)-n_bad}/{len(rows)} 正常，{n_bad} 退化/失败", flush=True)
    if a.out:
        json.dump(rows, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"→ {a.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
