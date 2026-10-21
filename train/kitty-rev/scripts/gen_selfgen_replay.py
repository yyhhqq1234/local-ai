#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_selfgen_replay.py -- build a generic replay set from the ABLITERATED model itself.

Why not reuse the official reasoning rows
    `data/large-mix/train.jsonl`'s reasoning category came from aligned Qwen, so
    its assistant turns carry the alignment voice.  Replaying them during local
    training would teach refusal straight back in and cancel the abliteration
    that is this model's core property.  Measured refusal-phrase rate on that
    data is 0.09% (§16 scan), so the lexical risk is small -- but the *style*
    prior is diffuse and cannot be filtered by regex.  Generating the replay
    from the model's own weights keeps the voice identical by construction.

What it does
    100 built-in non-sensitive prompts (math / code / logic) -> POST to an
    OpenAI-compatible endpoint (serve_4bit_base.py with base + adapter) ->
    temperature 0.7, max_new_tokens 512 -> refuse-phrase filter -> gen-selfgen.jsonl
    in the same schema as train.jsonl (messages + meta.cat = "gen-selfgen").

Usage
    python gen_selfgen_replay.py --base http://127.0.0.1:18000 \
        --model base-qwen3.8-27b --out train/kitty-rev/data/gen-selfgen.jsonl

    python gen_selfgen_replay.py --dry-run      # print prompts + request body, no network
"""
import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.request

REFUSAL_PATTERNS = [
    r"(抱歉|对不起|很遗憾)[，,].{0,12}(不能|无法|不便|不可以)",
    r"(作为|身为)(一个)?\s*(AI|人工智能|语言模型)",
    r"I (?:can't|cannot|am unable to|must decline)\s+(?:help|assist|provide|comply|support|do that|answer that|fulfill|engage|share)",
    r"I (?:can't|cannot)\s+(?:help|assist)\s+with\s+(?:that|this|such|these|requests?)",
    r"(违反|违背).{0,8}(政策|准则|规定|法律)",
    r"(不提供|不予).{0,6}(帮助|协助|支持).{0,6}(此类|这类|该)",
    r"(建议|请)(咨询|联系).{0,10}(专业人士|律师|相关部门)",
]


def is_refusal(text):
    for i, pat in enumerate(REFUSAL_PATTERNS):
        m = re.search(pat, text or "", re.I)
        if m:
            return True, i, m.group(0)[:60]
    return False, None, None


def build_prompts(total=100, seed=42):
    """Deterministic 100-item prompt list: math 40 / code 35 / logic 25.

    NOTE the parameter is `total`, not `n`: the math loops below use a local `n`
    for the integer they insert, and shadowing the arity argument silently
    truncated the list to whatever the last random int happened to be.
    """
    rng = random.Random(seed)
    prompts = []
    # --- math 40: arithmetic, percentage, algebra, probability -------------
    for _ in range(14):
        a, b = rng.randint(11, 99), rng.randint(11, 99)
        prompts.append((f"math", f"计算 {a} × {b}，写出你的计算步骤，最后一行只给结果。"))
    for _ in range(8):
        p, v = rng.choice([15, 20, 25, 30, 40]), rng.randint(40, 400)
        prompts.append(("math", f"{v} 的 {p}% 是多少？给出推导过程。"))
    for _ in range(8):
        a, b, c = rng.randint(2, 9), rng.randint(2, 20), rng.randint(2, 30)
        prompts.append(("math", f"解方程 {a}x + {b} = {c}，写出每一步。"))
    for _ in range(5):
        r, g = rng.randint(3, 8), rng.randint(3, 8)
        prompts.append(("math", f"一个袋子里有 {r} 个红球和 {g} 个蓝球，随机取一个，"
                                f"取到红球的概率是多少？用分数和小数两种形式给出。"))
    for _ in range(5):
        n = rng.randint(6, 30)
        prompts.append(("math", f"前 {n} 个正整数的和是多少？写出公式和代入过程。"))
    # --- code 35: write, debug, explain ------------------------------------
    for _ in range(10):
        name = rng.choice(["二分查找", "去重", "斐波那契", "字符串反转", "冒泡排序",
                           "快速排序", "最大公约数", "质数判断", "括号匹配", "矩阵转置"])
        prompts.append(("code", f"用 Python 实现{name}，加注释说明复杂度。"))
    for _ in range(10):
        snippet = rng.choice([
            "for i in range(len(x)):\n    if x[i] == 3: del x[i]",
            "def f(n): return f(n-1)*n",
            "d = {}\nfor k in keys: d[k] += 1",
            "s = ''\nfor w in words: s += w",
            "a = [1,2,3]\nfor i in range(4): print(a[i])",
            "x = []\nwhile x: x.pop(); x.append(1)",
            "def g(x): return x/0",
            "import json\njson.loads('{a:1}')",
            "for i in range(10):\n    for j in range(10):\n        if i==j: pass",
            "def h(*a): return h(*a)",
        ])
        prompts.append(("code", f"这段代码有什么问题？给出修正版并说明原因：\n```\n{snippet}\n```"))
    for _ in range(8):
        topic = rng.choice(["GIL", "闭包", "装饰器", "生成器", "浅拷贝与深拷贝",
                            "垃圾回收", "上下文管理器", "协程"])
        prompts.append(("code", f"解释 Python 的{topic}，给一个最小可运行例子。"))
    for _ in range(7):
        prompts.append(("code", "把这段逻辑改成不使用递归的写法，并说明为什么这样更快：\n"
                                "```\ndef walk(node):\n    if node is None: return 0\n"
                                "    return 1 + walk(node.left) + walk(node.right)\n```"))
    # --- logic 25: reasoning, sets, sequences ------------------------------
    for _ in range(9):
        a, b = rng.randint(2, 20), rng.randint(2, 20)
        prompts.append(("logic", f"若 A 蕴含 B，且 B 不成立，那么 A 是否成立？"
                                 f"用 {a} 和 {b} 造一个具体例子说明。"))
    for _ in range(8):
        n = rng.randint(3, 9)
        prompts.append(("logic", f"集合 {{1,...,{n}}} 有多少个子集？写出推导。"))
    for _ in range(8):
        d, r = rng.randint(2, 5), rng.randint(2, 4)
        prompts.append(("logic", f"首项 {d}、公差 {r} 的等差数列，前 10 项和是多少？写出公式。"))
    return prompts[:total]


def post(base, model, prompt, temperature, max_new, timeout=180):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_new,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.loads(r.read().decode("utf-8", "replace"))
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or ""


def main():
    ap = argparse.ArgumentParser(description="generate a generic replay set from the abliterated model")
    ap.add_argument("--base", default="http://127.0.0.1:18000")
    ap.add_argument("--model", default="base-qwen3.8-27b")
    ap.add_argument("--out", default="train/kitty-rev/data/gen-selfgen.jsonl")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-new", type=int, default=512)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-chars", type=int, default=80,
                    help="过短的回复丢弃（模型没答完整）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    prompts = build_prompts(a.n, a.seed)
    kinds = {}
    for k, _ in prompts:
        kinds[k] = kinds.get(k, 0) + 1
    print(f"[prompts] {len(prompts)} 条  {kinds}")

    if a.dry_run:
        print("[dry-run] 前 3 条：")
        for k, p in prompts[:3]:
            print(f"  [{k}] {p[:90]}")
        body = json.dumps({"model": a.model,
                           "messages": [{"role": "user", "content": prompts[0][1]}],
                           "temperature": a.temperature, "max_tokens": a.max_new,
                           "stream": False}, ensure_ascii=False)
        print(f"[dry-run] 请求体样例：POST {a.base}/v1/chat/completions  "
              f"{len(body.encode())} B")
        print(f"[dry-run] 输出将写 {a.out}，schema 同 train.jsonl，meta.cat=gen-selfgen")
        print("DRY_RUN_OK")
        return 0

    rows, refused, short, failed = [], 0, 0, 0
    t0 = time.time()
    for i, (kind, prompt) in enumerate(prompts, 1):
        try:
            txt = post(a.base, a.model, prompt, a.temperature, a.max_new)
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(prompts)}] {kind:5s} request failed: {e}")
            continue
        bad, _pi, hit = is_refusal(txt)
        if bad:
            refused += 1
            print(f"[{i}/{len(prompts)}] {kind:5s} 拒答命中「{hit}」→ 丢弃")
            continue
        if len(txt.strip()) < a.min_chars:
            short += 1
            print(f"[{i}/{len(prompts)}] {kind:5s} 过短 {len(txt.strip())}<{a.min_chars} → 丢弃")
            continue
        rows.append({
            "messages": [{"role": "user", "content": prompt},
                         {"role": "assistant", "content": txt}],
            "meta": {"cat": "gen-selfgen", "tier": "selfgen", "topic": kind,
                     "model": a.model, "temperature": a.temperature},
        })
        if i % 10 == 0:
            print(f"[{i}/{len(prompts)}] kept={len(rows)} refused={refused} "
                  f"short={short} failed={failed} {(time.time() - t0) / i:.1f}s/条")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    h = hashlib.sha256(open(a.out, "rb").read()).hexdigest()[:16]
    print(f"[done] {len(rows)}/{len(prompts)} 条 → {a.out}  sha16={h}  "
          f"refused={refused} short={short} failed={failed}  {(time.time() - t0) / 60:.1f} min")
    print(f"[判据] 拒答过滤后剩余率 {len(rows) / max(1, len(prompts)) * 100:.1f}%；"
          f"若 <60% 说明该端点仍带强对齐倾向，不要用它的回放数据")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
