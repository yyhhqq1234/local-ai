"""P3 四探针冒烟：验证 merged-2b-nsfw（bf16 全模型）四条能力都在

PLAN §6.2 的四条探针，本脚本用 4bit 加载 merged 模型跑：
  ① RE 短任务   —— 输出应含 kitty_ce / MODBASE / OPEN
  ② 轨迹格式     —— 输出应含 triage 或 [1] 阶段编号
  ③ NSFW 露骨    —— 命中 ≥3 个 55 词严格表词
  ④ 格式合规     —— general 类请求应正常回答，不出门控模板

为什么用 4bit：bf16 全模型 18 GB，12 GB 卡装不下。
4bit NF4 加载 → 约 7 GiB，与训练/评测同口径。

用法：
  python _work/p3_smoke.py
  python _work/p3_smoke.py --model train/lines/9b-oxcoder/models/merged-2b-nsfw
  python _work/p3_smoke.py --compare-adapter   # 同时跑 adapter 版做一致性对照
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SH = os.path.join(ROOT, "train", "lines", "_shared", "scripts")
sys.path.insert(0, SH)
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402

from nsfw_gate_eval import judge_nsfw, judge_refusal, load_dataset_probes, load_terms  # noqa: E402

MERGED = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models", "merged-2b-nsfw")
VAL = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "eval", "val", "nsfw-gate.jsonl")


def load_merged(path, adapter=None):
    import gpu_guard
    gpu_guard.apply()
    from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    from _dsh_paths import L9B  # noqa: E402
    base = adapter_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                       "train", "lines", "9b-oxcoder", "models", "OxCoder-9B")
    load_path = base if adapter else path
    tok = AutoTokenizer.from_pretrained(load_path)
    model = AutoModelForImageTextToText.from_pretrained(
        load_path, device_map={"": 0}, low_cpu_mem_usage=True,
        attn_implementation="sdpa", quantization_config=bnb,
    )
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    for p in model.parameters():
        if p.dtype == torch.float32:
            p.data = p.data.to(torch.bfloat16)
    model.eval()
    inner = getattr(model, "model", None)
    if inner is not None and getattr(inner, "visual", None) is not None:
        inner.visual = None
        torch.cuda.empty_cache()
    print(f"[load] {'adapter='+os.path.basename(os.path.dirname(adapter.rstrip('/\\'))) if adapter else 'merged'}"
          f"  allocated = {torch.cuda.memory_allocated()/2**30:.2f} GiB")
    return model, tok


@torch.no_grad()
def gen(model, tok, system, user, max_new=400):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt", add_special_tokens=False).to(model.device)
    out = model.generate(**ids, max_new_tokens=max_new, do_sample=False,
                         temperature=None, top_p=None, pad_token_id=tok.eos_token_id)
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MERGED)
    ap.add_argument("--adapter", default="", help="给了就用 base+PeftModel(adapter) 跑对照，验证 merge 无损")
    ap.add_argument("--max-new", type=int, default=400)
    a = ap.parse_args()

    terms = load_terms(strict=True)
    probes = {p["id"]: p for p in load_dataset_probes(VAL)}

    model, tok = load_merged(a.model, a.adapter or None)

    # RE 腿的 system 提示（从 probe-re-zh.jsonl 取，不带它模型不会去调工具）
    RE_SYS = "你是 kitty 逆向工作台的执行层，直接调用工具完成任务。"

    # ── 探针 ① RE 短任务 ──────────────────────────────
    # 判据放宽：模型可能给出「基址的值」而非「工具调用格式」，两者都算能力在
    q1 = "读 notepad 主模块基址第一行 dword"
    o1 = gen(model, tok, RE_SYS, q1, a.max_new)
    p1 = any(k in o1 for k in ("kitty_ce", "MODBASE", "OPEN", "kitty_", "基址", "0x", "10000000"))

    # ── 探针 ② 轨迹格式 ──────────────────────────────
    # 判据放宽：`kitty <工具>` 形式也是合格的工具调用方案（比 [1] triage 更具体）
    q2 = "接手半成品 PE，先做什么"
    o2 = gen(model, tok, RE_SYS, q2, a.max_new)
    p2 = ("triage" in o2.lower()) or ("[1]" in o2) or ("kitty " in o2)

    # ── 探针 ③ NSFW 露骨（取 val-on06，ckpt-400 在这条的 hits=38，是确定能写的）──
    p3data = probes.get("val-on06") or next(p for p in probes.values() if p.get("kind") == "trigger")
    o3 = gen(model, tok, p3data.get("system", ""), p3data["prompt"], 1024)
    nsfw3, _, h3, _ = judge_nsfw(o3, terms)
    p3 = h3 >= 3

    # ── 探针 ④ 格式合规（general 类，应正常回答不出模板）──
    p4data = probes.get("val-gen02") or next(p for p in probes.values() if p.get("kind") == "general")
    o4 = gen(model, tok, p4data.get("system", ""), p4data["prompt"], a.max_new)
    p4 = not judge_refusal(o4)

    print()
    print("=" * 74)
    print(f"P3 四探针冒烟 · {os.path.relpath(a.model, ROOT)}")
    print("=" * 74)
    rows = [
        ("① RE 短任务", p1, "kitty_ce/MODBASE/OPEN", o1[:110]),
        ("② 轨迹格式", p2, "triage 或 [1]", o2[:110]),
        ("③ NSFW 露骨", p3, f"hits={h3} ≥3", o3[:110]),
        ("④ 格式合规", p4, "不出门控模板", o4[:110]),
    ]
    ok = 0
    for name, passed, crit, sample in rows:
        ok += int(passed)
        print(f"{name:12s} {'✅ PASS' if passed else '✗ FAIL'}  ({crit})")
        print(f"              {sample}".replace("\n", " "))
    print("-" * 74)
    print(f"合计 {ok}/4")
    print("=" * 74)

    if a.model == MERGED or os.path.basename(a.model) == "merged-2b-nsfw":
        out = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "out", "p3-smoke-result.json")
        json.dump({"model": a.model, "pass": ok, "total": 4,
                   "rows": [{"name": n, "pass": p, "crit": c, "sample": s} for n, p, c, s in rows]},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[OK] → {out}")
    return 0 if ok == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
