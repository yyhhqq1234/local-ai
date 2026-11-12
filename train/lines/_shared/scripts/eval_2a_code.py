# -*- coding: utf-8 -*-
"""2A 判据 —— 编程轨迹（OpenHands 形态）的自动验收

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么不是 eval_2a_sequence.py（2026-10-29 实测后重写）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
原脚本假设 2A 数据是「kitty 多步工具编排」，据此写了工具序列 LCS 判据。
实测 2A 数据（traj-all-capped 16195 条）：
    assistant 含 kitty_/reverse_ 的只有 3 条（0.02%）
    满足「参考序列 ≥3 个 kitty 工具」的样本：0 条 → 脚本直接 FATAL
真实形态是 **OpenHands 编程 agent 轨迹**：
    system 94.4% = "You are OpenHands agent..."
    assistant = 长代码 / 技术分析文本（P50 2476 字符，P90 3468）
    任务 = 读仓库 → 定位 bug → 改文件 → 跑测试

所以判据要换成「编程任务做对没」，不能判工具序列。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四条判据（都不需要跑代码，可自动化）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
① **实体覆盖** entity_cov —— 最关键
     task 里给出的标识符（文件名/函数名/变量名/错误码），回答里提到了多少。
     没提到 = 没读懂任务，写得再长也是跑偏。
     判据：≥0.50 及格

② **代码块完整性** code_ok
    回答里 ``` 围栏是否成对闭合、有没有给出可改的代码。
     判据：≥80% 的条目 code_ok

③ **n-gram 记忆度** ngram20
    回答与训练集的 20-gram 重合率。
     判据：<0.40 健康（>0.60 = 在背训练样本）

④ **长度合理性** len_ratio
    生成长度 / 参考长度。过短（<0.2）= 敷衍，过长（>3.0）= 灌水。
     只报告不判定

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python eval_2a_code.py --adapter train/lines/9b-oxcoder/out/re-stage1-r3/final --out train/lines/9b-oxcoder/out/eval-2a-r3.json
  python eval_2a_code.py --adapter ""                            # 基座对照
  python eval_2a_code.py --adapter <path> --limit 10              # 只跑前 10 条
"""
import argparse
import difflib
import io
import json
import os
import re
import sys

import torch

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN_ROOT = os.path.dirname(HERE)
try:  # 双线目录单一真相源（2026-11-01 迁移后）
    from _dsh_paths import TRAIN as _TRAIN, L9B as _L9B, L27B as _L27B, SHARED as _SHARED
    TRAIN_ROOT = _TRAIN
except Exception:
    _L9B = _L27B = _SHARED = None

sys.path.insert(0, HERE)

BASE = os.path.join(_L9B, "models", "OxCoder-9B")
CASES = os.path.join(HERE, "eval_cases_2a.py")
TRAJ = os.path.join(_L9B, "data", "agent-traj", "traj-all-capped.jsonl")
GIB = 2 ** 30

# 2A 的 system —— 方案 A（2026-10-29）
# ★ 常量移到 sys_prompts.py（单一真相源，训练数据替换脚本也 import 它）
#   原因：数据 assistant 是长代码分析文本，但原来的 "You are OpenHands agent"
#   system 会触发 base 的 agent 记忆 → 模型去调 read 工具而不写分析。
#   实测：原 system 覆盖 24.8% / 代码 2.5% → 换成 SYSTEM_2A 后 60.0% / 40.0%
from sys_prompts import SYSTEM_2A   # noqa: E402


def load_system_orig():
    """数据里原本的 system（保留备查，不用于评测）"""
    try:
        with io.open(TRAJ, encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                s = next((m["content"] for m in o.get("messages") or []
                          if m.get("role") == "system"), "")
                if s.strip():
                    return s
    except Exception:
        pass
    return "You are OpenHands agent, a helpful AI assistant that can interact with a computer."


def load_system():
    """评测用 system = SYSTEM_2A（与 2A 训练数据使用的 system 一致）"""
    return SYSTEM_2A


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def load_model(adapter=None):
    import gpu_guard
    gpu_guard.apply()
    from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForImageTextToText.from_pretrained(
        BASE, device_map={"": 0}, low_cpu_mem_usage=True,
        attn_implementation="sdpa", quantization_config=bnb,
    )
    if adapter:
        model = PeftModel.from_pretrained(model, adapter)
    for p in model.parameters():
        if p.dtype == torch.float32:
            p.data = p.data.to(torch.bfloat16)
    model.eval()
    inner = getattr(model, "model", None)
    if inner is not None and getattr(inner, "visual", None) is not None:
        inner.visual = None
        torch.cuda.empty_cache()
    print("[load] %s  allocated = %.2f GiB"
          % ("adapter" if adapter else "base", torch.cuda.memory_allocated() / GIB))
    return model, tok


@torch.no_grad()
def gen(model, tok, system, user, max_new=800, max_in=4500):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt", add_special_tokens=False).to(model.device)
    if ids["input_ids"].shape[1] > max_in:
        ids = {"input_ids": ids["input_ids"][:, :max_in],
               "attention_mask": ids["attention_mask"][:, :max_in]}
    out = model.generate(
        **ids, max_new_tokens=max_new, do_sample=False,
        temperature=None, top_p=None, pad_token_id=tok.eos_token_id,
    )
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def code_blocks(text):
    """返回 (完整块数, 是否全部闭合)"""
    fences = re.findall(r"```", text or "")
    n = len(fences) // 2
    return n, (len(fences) % 2 == 0 and n > 0)


def entity_cov(resp, must):
    """must_mention 里的标识符在回答里出现了多少"""
    if not must:
        return 1.0, []
    low = (resp or "").lower()
    miss = [m for m in must if m.lower() not in low]
    return (len(must) - len(miss)) / len(must), miss


def ngram_overlap(a, b, n=20):
    """20-gram 重合率（记忆度指标）"""
    A, B = (a or ""), (b or "")
    if len(A) < n or len(B) < n:
        return 0.0
    ga = {A[i:i + n] for i in range(len(A) - n + 1)}
    gb = {B[i:i + n] for i in range(len(B) - n + 1)}
    return len(ga & gb) / max(len(ga), 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="train/lines/9b-oxcoder/out/re-stage1-r3/final")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--max-new", type=int, default=800)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from eval_cases_2a import CASES as ALL
    cases = ALL[:args.limit] if args.limit else ALL

    system = load_system()
    print("=" * 80)
    print("2A 编程轨迹验收 —— 实体覆盖 / 代码完整 / 记忆度")
    print("=" * 80)
    print("cases=%d | adapter=%s" % (len(cases), args.adapter or "base"))
    print()

    model, tok = load_model(args.adapter)

    covs, code_oks, ngrams, ratios = [], [], [], []
    detail = []
    for i, c in enumerate(cases, 1):
        resp = gen(model, tok, system, c["ask"], args.max_new)
        cov, miss = entity_cov(resp, c.get("must_mention") or [])
        nb, ok = code_blocks(resp)
        ng = ngram_overlap(resp, c.get("ref") or "")
        ratio = (len(resp) / max(len(c.get("ref") or "x"), 1))
        covs.append(cov)
        code_oks.append(1 if ok else 0)
        ngrams.append(ng)
        ratios.append(ratio)
        detail.append({"id": c["id"], "level": c.get("level"), "cov": round(cov, 3),
                       "miss": miss[:5], "code_blocks": nb, "code_ok": ok,
                       "ngram20": round(ng, 3), "len_ratio": round(ratio, 2),
                       "resp_head": resp[:200]})
        mark = "✅" if cov >= 0.5 and ok else ("△" if cov >= 0.3 else "❌")
        print("  [%s] %-4s %-3s 覆盖 %.0f%% (缺 %s) | 代码块 %d%s | ngram %.2f | 长度比 %.2f"
              % (mark, c["id"], c.get("level", "?"), cov * 100,
                 ",".join(miss[:3]) or "无", nb, "" if ok else "(未闭合)",
                 ng, ratio))

    n = len(cases)
    avg_cov = sum(covs) / n
    code_rate = sum(code_oks) / n
    avg_ng = sum(ngrams) / n
    print()
    print("=" * 80)
    print("汇总（%d 条）" % n)
    print("=" * 80)
    print("  实体覆盖率均值   %.1f%%   （判据 >=50%%）" % (avg_cov * 100))
    print("  代码块完整率     %.1f%%   （判据 >=80%%）" % (code_rate * 100))
    print("  20-gram 重合     %.3f    （判据 <0.40 健康 / >0.60 背答案）" % avg_ng)
    print("  平均长度比       %.2f" % (sum(ratios) / n))
    print()
    ok1 = avg_cov >= 0.50
    ok2 = code_rate >= 0.80
    # ★ ngram 不作判定：泛化集是自造任务，与训练集不同源，
    #   「与参考答案相似度」只能说明有没有给出实质内容，不能当记忆度用。
    #   记忆度要用「训练集内部抽样，训前 vs 训后对比」（见 ANTI-MEMORIZATION.md）。
    print("  判定：实体覆盖 %s | 代码完整 %s | （参考相似度仅报告）"
          % ("✅" if ok1 else "❌", "✅" if ok2 else "❌"))
    verdict = ok1 and ok2
    print("  本轮：%s" % ("✅ 通过" if verdict else "❌ 不通过"))

    out = args.out or os.path.join(_L9B, "out", "eval-2a.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump({"adapter": args.adapter, "n": n, "avg_cov": round(avg_cov, 4),
               "code_rate": round(code_rate, 4), "avg_ngram20": round(avg_ng, 4),
               "verdict": verdict, "detail": detail},
              io.open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n  → 明细 %s" % out)
    sys.exit(0 if verdict else 1)


if __name__ == "__main__":
    main()
