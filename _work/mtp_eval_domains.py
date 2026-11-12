"""MTP 能力分域评估：训在 RE 数据上的 MTP，换到别的数据分布还剩多少

为什么需要：
  训练只用了 mix-z-re-v2-cand-train.jsonl（RE 工具调用，7,184 条）
  风险 = MTP 过拟合到「kitty 工具调用」这一种文本分布，
        换到门控创作 / 通用问答时接受率掉（top-1 下降）

指标：
  top-1 / top-3 / top-5 准确率
    top-k = 给定主干 hidden + 下一 token embedding，MTP 的 top-k 里是否命中真实下一 token
    top-1 近似 temperature→0 的投机解码接受率
    top-3/top-5 近似 temperature>0 时的接受率上界

用法：
  python _work/mtp_eval_domains.py                 # 默认三域各 60 条
  python _work/mtp_eval_domains.py --n 40          # 每域 40 条（更快）
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SH = os.path.join(ROOT, "train", "lines", "_shared", "scripts")
sys.path.insert(0, SH)
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "27b-kittyrev", "quant"))
sys.stdout.reconfigure(encoding="utf-8")

import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from pathlib import Path  # noqa: E402

from mtp_posttrain import MTPLayer, cfg_from_checkpoint  # noqa: E402

BASE = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models", "merged-2b-nsfw")
TUNED = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models", "mtp",
                     "merged-2b-nsfw-mtp-tuned.safetensors")
OFFICIAL = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "models", "mtp",
                        "qwen3.5-9b-mtp.safetensors")

_VAL = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "eval", "val", "nsfw-gate.jsonl")
# (显示名, 路径, meta.kind 筛选取值 | None=全取)
DOMAINS = [
    ("RE(工具调用)", os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "kitty-reverse",
                              "mix-z-re-v2-cand-train.jsonl"), None),
    ("门控(NSFW 训练集)", os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated",
                                   "train-2b-gated-v5.jsonl"), None),
    ("创作(val gate-on)", _VAL, {"gate-on"}),
    ("通用(val general)", _VAL, {"general"}),
]


def load_rows(path, n, kind_filter=None, skip=0):
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < skip:
                continue
            d = json.loads(line)
            if kind_filter:
                k = (d.get("meta") or {}).get("kind") or d.get("kind")
                if k not in kind_filter:
                    continue
            msgs = d.get("messages") or []
            if len(msgs) < 2:
                continue
            rows.append(d)
            if len(rows) >= n:
                break
    return rows


@torch.no_grad()
def eval_domain(mtp, base, tok, embed, lm_head, rows, ctx=2048, label=""):
    hit1 = hit3 = hit5 = tot = 0
    for r in rows:
        txt = "\n".join(m.get("content", "") for m in r.get("messages", []))
        ids = tok(txt, return_tensors="pt", truncation=True, max_length=ctx).input_ids
        if ids.shape[1] < 8:
            continue
        ids = ids.to(base.device)
        o = base(ids, output_hidden_states=True)
        T = ids.shape[1] - 2
        h = o.hidden_states[-1][:, :T].float()
        e = embed(ids[:, 1:T + 1]).float()
        logits = mtp(h, e, base_lm_head=lm_head)
        target = ids[:, 2:T + 2]
        top5 = logits.topk(5, dim=-1).indices          # [B,T,5]
        tgt = target.unsqueeze(-1)                      # [B,T,1]
        hit1 += (top5[..., 0] == target).sum().item()
        hit3 += (top5[..., :3] == tgt).any(-1).sum().item()
        hit5 += (top5[..., :5] == tgt).any(-1).sum().item()
        tot += target.numel()
    if tot == 0:
        return None
    return {"domain": label, "n_tokens": tot,
            "top1": round(hit1 / tot, 4), "top3": round(hit3 / tot, 4), "top5": round(hit5 / tot, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--mtp", default=TUNED)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--ctx", type=int, default=2048)
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from safetensors.torch import load_file

    ckpt = Path(a.base)
    cfg = cfg_from_checkpoint(ckpt)
    sd = load_file(a.mtp)
    print(f"[mtp] {os.path.basename(a.mtp)} · {len(sd)} 张量", file=sys.stderr)

    tok = AutoTokenizer.from_pretrained(str(ckpt), trust_remote_code=True)
    base = AutoModelForCausalLM.from_pretrained(str(ckpt), torch_dtype=torch.bfloat16,
                                               device_map="auto", trust_remote_code=True)
    base.eval()
    for p in base.parameters():
        p.requires_grad_(False)
    mtp = MTPLayer(cfg, sd).to(next(base.parameters()).device, dtype=torch.float32)
    mtp.eval()
    lm_head = base.get_output_embeddings()
    embed = base.get_input_embeddings()

    results = []
    for name, path, kind_filter in DOMAINS:
        if not os.path.exists(path):
            print(f"[skip] {name}: 文件不存在", file=sys.stderr)
            continue
        rows = load_rows(path, a.n, kind_filter=kind_filter, skip=0)
        print(f"[eval] {name}: {len(rows)} 条", file=sys.stderr)
        if not rows:
            continue
        res = eval_domain(mtp, base, tok, embed, lm_head, rows, a.ctx, name)
        if res:
            results.append(res)
            print(f"  {name:22s} top1={res['top1']:.4f}  top3={res['top3']:.4f}  "
                  f"top5={res['top5']:.4f}  (tokens {res['n_tokens']})", file=sys.stderr)

    print()
    print("=" * 76)
    print(f"MTP 分域能力 · {os.path.basename(a.mtp)}")
    print("=" * 76)
    print(f"{'数据域':22s} {'top-1':>8s} {'top-3':>8s} {'top-5':>8s} {'tokens':>10s}")
    print("-" * 76)
    for r in results:
        print(f"{r['domain']:22s} {r['top1']:8.4f} {r['top3']:8.4f} {r['top5']:8.4f} {r['n_tokens']:10d}")
    print("=" * 76)

    if a.out:
        json.dump({"mtp": a.mtp, "base": a.base, "results": results},
                  open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"[OK] → {a.out}")


if __name__ == "__main__":
    main()
