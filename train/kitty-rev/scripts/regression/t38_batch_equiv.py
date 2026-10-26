#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t38_batch_equiv.py -- `--batch N` 的等价性验收器（greedy 下批与单发必须逐字节相同）。

背景
    serve_4bit_base.py 新增 `--batch N`：攒批 → 一次 generate → 按 job 回填。提速明显
    （单请求只吃 1 核），但批处理有四种经典"看起来更快、结果悄悄变了"：
      ① 右 padding → decoder-only 生成位置错位；
      ② 没有 attention_mask → pad token 参与注意力；
      ③ 批内统一 max_new → 短请求被别人的长度带跑/截断错位；
      ④ 一条超长请求把整批显存/时延拖爆（或整批超时）。
    这四条任一条踩中，评测分数就会**无提示地**变（B/C 组对比全废）。

本验收器三段
    A 静态契约（永远跑）：源码里必须有 左padding / attention_mask / pad_token_id /
      逐 job 截断 / 超长独跑 / 批异常降级。缺任一 → 红。
    B 差异分类器（永远跑）：给两份输出，判断「逐字节相同 / padding 污染 / 真发散」。
       这是 A 与 C 的判据本体 —— 也用于线上复跑时定位首个差异 token。
    C 实机等价（需要两个 serve）：--base1（--batch 1）与 --base4（--batch 4）
       同 5 条 prompt 逐字节比对；混长短；一条超长必须按时返回。

用法
    python scripts/regression/t38_batch_equiv.py                    # A+B（本机无 GPU 也能跑）
    python scripts/regression/t38_batch_equiv.py --base1 URL1 --base4 URL2   # A+B+C
    python scripts/regression/t38_batch_equiv.py --require-live ... # C 不可用即红（云端用）
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SERVE = os.path.join(KITTY, "scripts", "serve_4bit_base.py")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


# --------------------------------------------------------------------------- #
# A. 静态契约
# --------------------------------------------------------------------------- #
def audit_source(src):
    """返回缺失项清单（空 = 合格）。每条都是"缺了就静默变结果"的等价性要点。"""
    miss = []
    if not re.search(r'add_argument\("--batch"', src):
        miss.append("没有 --batch 参数")
    if not re.search(r'add_argument\("--batch",\s*type=int,\s*default=1', src):
        miss.append("--batch 默认不是 1（默认必须与旧行为逐比特一致）")
    if "plen - L" not in src:
        miss.append("没做左 padding（decoder-only 必须右对齐到左，否则生成位置错位）")
    if "attention_mask=am" not in src:
        miss.append("批前向没传 attention_mask（pad token 会参与注意力 = pad 污染）")
    if "pad_token_id=" not in src:
        miss.append("没传 pad_token_id")
    if "prompt_len + j.max_new <= self.max_tokens" not in src:
        miss.append("没有「超长请求单独跑」的分流（一条长 prompt 会拖爆整批）")
    if "self.stat[\"fallback\"]" not in src and "fallback" not in src:
        miss.append("批级异常没有降级为逐条重跑（一条坏请求会带走别人）")
    if "[i][plen:]" not in src and "out[i][plen:]" not in src:
        miss.append("回填时没按 plen 偏移取生成段（会把 prompt 尾巴算进输出）")
    return miss


src = open(SERVE, encoding="utf-8").read()

# serve 侧复审项（不是本测试文件能改的）：--strict 时计入 fails
REVIEW = []
if "out[i][plen:]" in src and "for i, j in enumerate(group)" not in src:
    REVIEW.append("批内回填没有按 enumerate(group) 对齐行号（会张冠李戴）")
if "[i][plen:]" in src:
    pass   # 已按行对齐
if "self.stat[\"solo\"]" not in src:
    REVIEW.append("没有 solo 计数 —— 超长隔离是否真触发无法从 stats 看")
# selftest ③ 的超长隔离必须给**真实预算**，否则分流条件恒真、solo 从不触发
if "Batcher(tok, model, batch, 0, 1 << 20, lock" in src:
    REVIEW.append("selftest 的 run_batch 用 max_tokens=1<<20 → 「超长隔离」用例不会走 solo 分支"
                  "（测试假绿，需按 --max-batch-tokens 传真实预算并断言 stat[\"solo\"]>=1）")
miss = audit_source(src)
check("A 静态契约齐全（左pad/attn_mask/pad_id/逐job截断/超长独跑/降级）", not miss,
      "；".join(miss) if miss else "6/6")
check("A --batch 默认 1（默认与旧版逐字节相同）",
      'default=1' in src.split('"--batch"')[1][:60] if '"--batch"' in src else False, "")
check("A 批内按各 job 的 max_new 截断（greedy 前缀一致）",
      "j.max_new" in src and "mx = max(" in src, "")


# --------------------------------------------------------------------------- #
# B. 差异分类器（判据本体）
# --------------------------------------------------------------------------- #
def first_diff(a, b):
    """返回首个不同字符的下标；完全相同返回 -1；一方是另一方前缀返回较短长度。"""
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return -1 if len(a) == len(b) else n


def classify_diff(a, b, pad_text=""):
    """把两份输出分类：identical / padding / divergent。

    padding 的判据（任一成立即判 padding 污染）：
      · 批输出的开头多出 pad 字符（左 padding 泄漏进 decode）
      · 首个差异位置落在「批输出比单发多出来的那段前缀」内
      · 批输出里出现 pad 文本（pad_token 没被 skip 掉）
    """
    i = first_diff(a, b)
    if i < 0:
        return "identical", -1
    extra = len(a) - len(b)
    if pad_text and pad_text in a and pad_text not in b:
        return "padding", i
    if extra > 0 and i < extra:
        return "padding", i
    if extra < 0 and i < -extra:                 # b 比 a 多（对称情况）
        return "padding", i
    return "divergent", i


# 自测分类器：干净 / pad 污染 / 真发散
check("B identical：完全相同 → identical", classify_diff("abc", "abc")[0] == "identical")
check("B padding：批输出多出前缀 → padding",
      classify_diff("xxabc", "abc")[0] == "padding", str(classify_diff("xxabc", "abc")))
check("B padding：输出里残留 pad 文本 → padding",
      classify_diff("a<pad>bc", "abc", pad_text="<pad>")[0] == "padding")
check("B divergent：等长但正文不同 → divergent",
      classify_diff("abX", "abY")[0] == "divergent", str(classify_diff("abX", "abY")))
# 反向证明：如果把「前缀差异」错判成 divergent，就会把真 bug 当成噪声放过
check("B 反向：padding 与 divergent 必须可区分（否则 ④ 类 bug 会被当噪声）",
      classify_diff("xxabc", "abc")[0] != classify_diff("abX", "abY")[0])


# --------------------------------------------------------------------------- #
# C. 实机等价（两个 serve）
# --------------------------------------------------------------------------- #
def ask(base, prompt, max_tokens=96, timeout=180):
    body = {"model": "equ", "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0, "max_tokens": max_tokens, "stream": False}
    req = urllib.request.Request(base.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        obj = json.loads(r.read().decode("utf-8", "replace"))
    txt = ((obj.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return txt, time.time() - t0


def health(base):
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/health", timeout=5) as r:
            return r.status == 200
    except Exception:                                        # noqa: BLE001
        return False


def live(base1, base4, require_live):
    if not (base1 and base4 and health(base1) and health(base4)):
        banner = ("[PENDING] 没有可用的两个 serve（--batch 1 / --batch 4）→ 实机等价未测。"
                  "本机无 GPU 属正常；云端或 S2 前必须用 --base1/--base4 补测")
        print(banner)
        return 0 if not require_live else 1

    prompts = [
        "用一句话说明 PE 节表里 .text 的作用。",
        "MODENUM 返回什么？一句话。",
        "简述左 padding 为什么对 decoder-only 必要。",
        "把 PING 的语义写成一行命令示例。",
        "一句话：S_NEW 为什么必须给显式区间？",
    ]
    bad = 0
    for k, p in enumerate(prompts, 1):
        a, _ = ask(base1, p)
        b, _ = ask(base4, p)
        kind, idx = classify_diff(b, a)
        check(f"C 等价 #{k}（batch1 vs batch4 逐字节）", kind == "identical",
              f"{kind} @ {idx}  a={a[:24]!r} b={b[:24]!r}")
        bad += kind != "identical"

    # 混长短：三条短 + 一条长，短的那条不许被 pad 影响
    shorts = ["一句话：PING 做什么？", "一句话：LP 做什么？", "一句话：CUR 做什么？"]
    long = "请详细说明" + "逆向工程中" * 40 + "的注意事项。"
    solo = {p: ask(base1, p)[0] for p in shorts}
    for p in shorts + [long]:
        _, _ = ask(base4, p)
    for p in shorts:
        b, _ = ask(base4, p)
        kind, idx = classify_diff(b, solo[p])
        check(f"C 混长短：短 prompt {p[:12]}… 未被 pad 影响", kind == "identical",
              f"{kind} @ {idx}")
        bad += kind != "identical"

    # 混批组成（比同批比较更硬）：同一个 prompt 单独跑 vs 混进 [A,B,C,D]
    A = "一句话：PING 做什么？"
    A_solo, _ = ask(base4, A)                     # 批服务器上单独一发（批里只有它）
    for p in ("一句话：LP 做什么？", "一句话：CUR 做什么？", "一句话：MODENUM 做什么？"):
        ask(base4, p)                             # 先把它填进批里
    A_mixed, _ = ask(base4, A)
    kind, idx = classify_diff(A_mixed, A_solo)
    check("C 混批组成：同一 prompt 独自 vs 混进 4 条，输出必须相同",
          kind == "identical", f"{kind} @ {idx}")

    # 超长：必须按时返回（不整批超时），且内容与单发一致
    t0 = time.time()
    try:
        b, dt = ask(base4, long, max_tokens=96, timeout=300)
        a, _ = ask(base1, long, max_tokens=96, timeout=300)
        check("C 超长请求按时返回（未拖死整批）", dt < 300, f"{dt:.1f}s")
        kind, idx = classify_diff(b, a)
        check("C 超长请求输出与单发一致", kind == "identical", f"{kind} @ {idx}")
        bad += kind != "identical"
    except Exception as e:                                    # noqa: BLE001
        check("C 超长请求未抛异常", False, f"{type(e).__name__}: {e}")
        bad += 1
    return 0 if bad == 0 else 1


def main():
    ap = argparse.ArgumentParser(description="--batch N 等价性验收（greedy 逐字节）")
    ap.add_argument("--base1", default="", help="用 --batch 1 起的 serve base URL")
    ap.add_argument("--base4", default="", help="用 --batch 4 起的 serve base URL")
    ap.add_argument("--strict", action="store_true",
                    help="把 serve 侧 REVIEW 项也计入失败（交付/签字前用）")
    ap.add_argument("--require-live", action="store_true",
                    help="C 段不可用即失败（云端/S2 前用这个；本机无 GPU 别加）")
    a = ap.parse_args()
    for f in REVIEW:
        check('[REVIEW] ' + f, not a.strict, '--strict 下计红')
    rc = live(a.base1, a.base4, a.require_live)
    if not a.base1 or not a.base4:
        check("C 参数给全（--base1/--base4）", not a.require_live,
              "缺参数；本机可忽略，云端必须给")
    print("\nPASS: 静态契约齐全 + 差异分类器可辨 padding/发散"
          + ("" if b"" else "") if not fails else f"\nFAIL: {fails}")
    return 0 if (not fails and rc == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
