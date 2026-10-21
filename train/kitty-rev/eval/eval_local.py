#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""eval_local.py —— 本地 transformers 推理评测（不需要 ninfer 引擎、不占端口）

用途：用同一套行为判据（复用 eval_kitty.py 的 RULES）对比 base 与 adapter，
      在 8B 上验证"数据是否真的让行为变好"，为 27B 训练提供先验。

用法:
  python eval_local.py --model ../base/Qwen3-8B --data data/large-mix/eval.jsonl --limit 80 --out logs/eval-8b-base.json
  python eval_local.py --model ../base/Qwen3-8B --adapter out-mix/adapter --limit 80 --out logs/eval-8b-adapter.json

判据来源：eval/eval_kitty.py 的 RULES（tool-route / op-syntax / transition-syntax / guard / rubric 等）
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "eval"))

import eval_kitty as EK   # 复用判据表与合同加载


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--adapter", default="")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "large-mix", "eval.jsonl"))
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--out", default="")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    print(f"[load] {a.model}" + (f" + adapter {a.adapter}" if a.adapter else ""))
    tok = AutoTokenizer.from_pretrained(a.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(a.model, quantization_config=bnb,
                                                dtype=torch.bfloat16, device_map="auto",
                                                trust_remote_code=True)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()

    rows = []
    with open(a.data, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows = rows[: a.limit] if a.limit else rows
    print(f"[data] {len(rows)} 条")

    by_cat, results = {}, []
    t0 = time.time()
    for i, row in enumerate(rows, 1):
        cat = (row.get("meta") or {}).get("cat", "?")
        user = row["messages"][0]["content"]
        msgs = [{"role": "user", "content": user}]
        text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        inputs = tok(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=a.max_new_tokens,
                                 do_sample=False, pad_token_id=tok.pad_token_id)
        gen = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        ok, why = EK.judge(row, gen, [])
        by_cat.setdefault(cat, {"n": 0, "ok": 0})
        by_cat[cat]["n"] += 1
        by_cat[cat]["ok"] += 1 if ok else 0
        results.append({"i": i, "cat": cat, "pass": bool(ok), "why": str(why)[:120],
                        "chars": len(gen)})
        flag = "PASS" if ok else "FAIL"
        print(f"[{i}/{len(rows)}] {cat:24s} {flag} {str(why)[:70]}", flush=True)

    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    print("\n" + "=" * 60)
    print(f"{a.tag or os.path.basename(a.model)}: {passed}/{total} = {passed/max(1,total)*100:.1f}%  "
          f"用时 {(time.time()-t0)/60:.1f} min")
    for c, v in sorted(by_cat.items(), key=lambda x: -x[1]["n"]):
        print(f"  {c:26s} {v['ok']}/{v['n']}")

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        json.dump({"tag": a.tag or a.model, "model": a.model, "adapter": a.adapter,
                   "pass": passed, "total": total,
                   "byCat": {k: v for k, v in by_cat.items()}, "detail": results},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"[ok] → {a.out}")


if __name__ == "__main__":
    main()
