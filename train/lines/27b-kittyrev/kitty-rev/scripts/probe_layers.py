#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""probe_layers.py -- where does the 27B actually keep its reverse-engineering ability?

Four independent evidence streams, each persisted per layer so a 64-layer run can
be split into segments and merged later:

  ① logit lens   per layer: final_norm + lm_head -> top-5 tokens at the last
                 position, plus "convergence layer" = first layer whose top-1
                 already equals the final layer's top-1
  ② linear probe last-token and mean-pooled hidden per layer -> 5-fold CV
                 accuracy for three label sets (pass/fail, cat, calls>0)
  ③ ablation     zero one layer's output, regenerate, compare pass/top-1/text
                 delta against the unablated run (default 16 sampled layers)
  ④ adapter      Frobenius and spectral norm of every LoRA pair, aggregated per
                 layer -- the direct evidence of where training put its energy

Modes
    --mode all             run ① ② ③ ④ then merge
    --mode logit,probe     subset
    --mode adapter         CPU only, no model load
    --mode merge           stitch per-layer json into the four summary files

Layer selection
    --layers all           every layer 0..63
    --layers 48-63         a segment (results merge with other segments)
    --layers 0,4,8,12      explicit list

Resume
    Every layer writes <out>/<mode>/layer_NN.json atomically-ish; an existing file
    is skipped unless --overwrite. So a timed-out run is restarted for free.

VRAM (4bit, device_map {"":0}, ctx 512)
    12.6 GiB weights + ~1 GiB KV + 2.4 GiB transient head + per-layer hidden that
    is copied to CPU immediately -> measured headroom well under 20 GiB.
    Hidden states are NEVER stacked on the GPU (that would be 7.4 GiB for 64x23).

Self-check
    --dry-run loads no weights: validates data/label alignment, layer parsing and
    the hook/shape contract on a CPU toy module.
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import sys
import time

import torch

TOK_RE = re.compile(r"[\w\u4e00-\u9fa5]+|[^\s\w]", re.U)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def human(n):
    return f"{n / 2 ** 30:.2f} GiB" if n >= 2 ** 30 else f"{n / 2 ** 20:.1f} MiB"


def parse_layers(spec, n_layers):
    spec = (spec or "all").strip().lower()
    if spec in ("all", "", "*"):
        return list(range(n_layers))
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    bad = [i for i in out if not (0 <= i < n_layers)]
    if bad:
        raise SystemExit(f"[FATAL] 层号越界 {bad[:5]}（共 {n_layers} 层）")
    return sorted(set(out))


def jdump(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def jload(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f):
            line = line.strip()
            if line:
                rows.append((ln, json.loads(line)))
    return rows


def parse_tool_calls(text):
    """Qwen3.5 XML form first, JSON fallback -- same contract as serve_4bit_base."""
    calls = []
    for m in re.finditer(r"<tool_call>\s*<function=([^>\n]+)>(.*?)</function>\s*</tool_call>",
                         text, re.S):
        args = {}
        for p in re.finditer(r"<parameter=([^>\n]+)>(.*?)</parameter>", m.group(2), re.S):
            args[p.group(1).strip()] = p.group(2).strip()
        calls.append({"name": m.group(1).strip(), "args": args})
    if calls:
        return calls
    for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", text, re.S):
        try:
            o = json.loads(m.group(1))
        except Exception:
            continue
        nm = o.get("name") or o.get("function")
        if nm:
            calls.append({"name": nm, "args": o.get("arguments") or {}})
    return calls


def text_similarity(a, b):
    ta, tb = TOK_RE.findall(a or ""), TOK_RE.findall(b or "")
    if not ta and not tb:
        return 1.0
    sa, sb = set(ta), set(tb)
    inter = len(sa & sb)
    return inter / max(1, len(sa | sb))


def load_eval_kitty(eval_dir):
    """Reuse the exact judges from eval_kitty.py so ablation pass/fail means the
    same thing as the 3/23 baseline."""
    path = os.path.join(eval_dir, "eval_kitty.py")
    if not os.path.exists(path):
        return None
    spec = importlib.util.spec_from_file_location("eval_kitty_probe", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# CV: sklearn if present, otherwise a small numpy logistic regression
# --------------------------------------------------------------------------- #
def _cv_accuracy_sklearn(X, y, folds=5):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    y = np.asarray(y)
    cls, cnt = np.unique(y, return_counts=True)
    if len(cls) < 2 or cnt.min() < folds:
        folds = max(2, int(cnt.min()))
    if cnt.min() < 2:
        return None
    skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    accs = []
    for tr, te in skf.split(X, y):
        pipe = make_pipeline(StandardScaler(),
                             LogisticRegression(max_iter=2000, C=1.0, multi_class="auto"))
        pipe.fit(X[tr], y[tr])
        accs.append(float((pipe.predict(X[te]) == y[te]).mean()))
    return sum(accs) / len(accs), accs


def _cv_accuracy_numpy(X, y, folds=5):
    """Multinomial logistic regression by full-batch gradient descent.

    23 samples x 5120 features: standardise, then fit. Not as tight as sklearn,
    but identical across environments and dependency-free.
    """
    import numpy as np
    y = np.asarray(y)
    cls = np.unique(y)
    if len(cls) < 2:
        return None
    idx = np.argsort(y, kind="stable")
    buckets = np.array_split(idx, folds)
    accs = []
    for k in range(folds):
        te = buckets[k]
        tr = np.concatenate([buckets[j] for j in range(folds) if j != k]) if folds > 1 else idx
        if len(np.unique(y[tr])) < 2 or len(te) == 0:
            continue
        Xtr, Xte = X[tr].astype(np.float64), X[te].astype(np.float64)
        mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
        Xtr = (Xtr - mu) / sd
        Xte = (Xte - mu) / sd
        Ytr = np.zeros((len(tr), len(cls)))
        pos = {c: i for i, c in enumerate(cls)}
        for i, v in enumerate(y[tr]):
            Ytr[i, pos[v]] = 1.0
        W = np.zeros((Xtr.shape[1], len(cls)))
        b = np.zeros(len(cls))
        lr, l2 = 0.5, 1e-2
        for _ in range(400):
            z = Xtr @ W + b
            z -= z.max(1, keepdims=True)
            p = np.exp(z)
            p /= p.sum(1, keepdims=True)
            g = (p - Ytr) / len(tr)
            W -= lr * (Xtr.T @ g + l2 * W)
            b -= lr * g.sum(0)
        pred = cls[np.argmax(Xte @ W + b, axis=1)]
        accs.append(float((pred == y[te]).mean()))
    return (sum(accs) / len(accs), accs) if accs else None


def cv_accuracy(X, y, folds=5):
    try:
        r = _cv_accuracy_sklearn(X, y, folds)
        if r is not None:
            return r, "sklearn"
    except Exception:
        pass
    r = _cv_accuracy_numpy(X, y, folds)
    return (r, "numpy") if r else (None, "numpy")


# --------------------------------------------------------------------------- #
# model / capture
# --------------------------------------------------------------------------- #
def build_model(args):
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    cfg = AutoConfig.from_pretrained(args.model, trust_remote_code=True)
    if not args.no_text_only:
        cfg.language_model_only = True
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True)
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(
        args.model, config=cfg, quantization_config=bnb, device_map={"": 0},
        dtype=torch.bfloat16, trust_remote_code=True)
    model.eval()
    if args.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
        model.eval()
        print(f"[load] adapter {args.adapter}")
    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    print(f"[load] {time.time() - t0:.1f}s  vram={torch.cuda.memory_allocated() / 2 ** 30:.2f} GiB")
    return model, tok, cfg


def backbone_of(model):
    for _n, m in model.named_modules():
        if hasattr(m, "layers") and hasattr(m, "norm"):
            return m
    raise SystemExit("[FATAL] 找不到 text backbone")


class HiddenTap:
    """Capture each decoder layer's OUTPUT and immediately move it to CPU.

    Keeping all 64 layers on the GPU would be 64 x 23 x 5 MB = 7.4 GiB on top of
    the weights; the CPU copy is ~320 MB and is all the probes need.
    """

    def __init__(self, layers, want, device):
        self.want = set(want)
        self.caps = {}
        self.handles = []
        for i, layer in enumerate(layers):
            if i in self.want:
                self.handles.append(layer.register_forward_hook(self._mk(i)))

    def _mk(self, idx):
        def hook(mod, inp, out):
            t = out[0] if isinstance(out, (tuple, list)) else out
            self.caps[idx] = t.detach().to("cpu", torch.bfloat16)
            return None
        return hook

    def reset(self):
        self.caps = {}

    def close(self):
        for h in self.handles:
            h.remove()
        self.handles = []


def make_zero_hook(idx, store):
    def hook(mod, inp, out):
        t = out[0] if isinstance(out, (tuple, list)) else out
        store["orig"] = t.detach()
        z = torch.zeros_like(t)
        if isinstance(out, (tuple, list)):
            return (z,) + tuple(out[1:])
        return z
    return hook


# --------------------------------------------------------------------------- #
# ① logit lens
# --------------------------------------------------------------------------- #
def _unused_run_logit_lens(model, tok, bb, caps, rows, layer_ids, out_dir, args):
    """Kept for reference only -- main() inlines a zero-extra-forward version that
    reuses the captured last-position hidden instead of re-running the model."""
    final = max(caps) if caps else max(layer_ids)
    summary = {}
    for L in sorted(caps):
        if os.path.exists(os.path.join(out_dir, "logit", f"layer_{L:02d}.json")) and not args.overwrite:
            continue
        per_prompt = []
        with torch.no_grad():
            for i, (_ln, row) in enumerate(rows):
                h = caps[L][:, -1:, :].to("cuda:0")
                h = bb.norm(h)
                logits = model.lm_head(h)[0, -1].float()
                p = torch.softmax(logits, dim=-1)
                top = torch.topk(p, 5)
                per_prompt.append({
                    "prompt_id": i,
                    "top5": [[tok.decode([int(t)], skip_special_tokens=True),
                              round(float(pv), 6)]
                             for t, pv in zip(top.indices.tolist(), top.values.tolist())],
                })
        os.makedirs(os.path.join(out_dir, "logit"), exist_ok=True)
        jdump(os.path.join(out_dir, "logit", f"layer_{L:02d}.json"),
              {"layer": L, "final_layer": final, "n_prompts": len(rows), "prompts": per_prompt})
        summary[L] = per_prompt
    # convergence layer: first L whose top-1 matches the last layer's top-1, for the majority of prompts
    if not os.path.exists(os.path.join(out_dir, "logit_lens.json")) or args.overwrite:
        merged = {}
        for p in glob.glob(os.path.join(out_dir, "logit", "layer_*.json")):
            d = jload(p) or {}
            if "layer" in d:
                merged[d["layer"]] = d["prompts"]
        if merged:
            top_layer = max(merged)
            conv = {}
            for i in range(len(rows)):
                ref = merged[top_layer][i]["top5"][0][0]
                first = None
                for L in sorted(merged):
                    if merged[L][i]["top5"][0][0] == ref:
                        first = L
                        break
                conv[i] = first
            vals = [v for v in conv.values() if v is not None]
            jdump(os.path.join(out_dir, "logit_lens.json"), {
                "final_layer": top_layer,
                "convergence": conv,
                "convergence_median": sorted(vals)[len(vals) // 2] if vals else None,
                "layers": {str(k): v for k, v in merged.items()},
            })
            print(f"[logit] 收敛层 median={sorted(vals)[len(vals) // 2] if vals else None} "
                  f"(最终层 {top_layer})")
    print(f"[logit] done {len(summary)} 层")


# --------------------------------------------------------------------------- #
# ② linear probe
# --------------------------------------------------------------------------- #
def run_probe(model, tok, bb, caps, rows, labels, layer_ids, out_dir, args):
    import numpy as np
    os.makedirs(os.path.join(out_dir, "probe"), exist_ok=True)
    n = len(rows)
    if labels is None or len(labels) < n:
        print(f"[probe][warn] 标签不足（{0 if labels is None else len(labels)} < {n}），跳过")
        return
    y_pass = np.array([1 if labels[i].get("pass") else 0 for i in range(n)])
    cats = sorted({labels[i].get("cat", "?") for i in range(n)})
    y_cat = np.array([cats.index(labels[i].get("cat", "?")) for i in range(n)])
    y_calls = np.array([1 if int(labels[i].get("calls") or 0) > 0 else 0 for i in range(n)])
    tasks = {"pass": y_pass, "cat": y_cat, "calls_gt0": y_calls}
    print(f"[probe] 标签: pass={int(y_pass.sum())}/{n} cats={cats} calls>0={int(y_calls.sum())}/{n}")

    for L in sorted(caps):
        dst = os.path.join(out_dir, "probe", f"layer_{L:02d}.json")
        if os.path.exists(dst) and not args.overwrite:
            continue
        h = caps[L]                              # [1, T, H] bf16 on CPU, one prompt at a time
        # caps holds only the LAST prompt when reused; the caller accumulates instead
        X_last = h["last"].float().numpy()       # [n, H]
        X_mean = h["mean"].float().numpy()       # [n, H]
        rec = {"layer": L, "n": n, "tasks": {}}
        for tname, y in tasks.items():
            for pool, X in (("last", X_last), ("mean", X_mean)):
                r, impl = cv_accuracy(X, y, folds=min(5, int(np.bincount(y).min()) or 2))
                if r is None:
                    rec["tasks"][f"{tname}|{pool}"] = {"acc": None, "why": "单一类别或样本不足"}
                else:
                    rec["tasks"][f"{tname}|{pool}"] = {"acc": round(r[0], 4),
                                                       "folds": [round(x, 4) for x in r[1]],
                                                       "impl": impl}
        jdump(dst, rec)
        best = max((v.get("acc") or 0) for v in rec["tasks"].values())
        print(f"[probe] L{L:02d} best_acc={best:.3f}")
    # summary curves
    if not os.path.exists(os.path.join(out_dir, "probe_acc.json")) or args.overwrite:
        curves = {}
        for p in sorted(glob.glob(os.path.join(out_dir, "probe", "layer_*.json"))):
            d = jload(p) or {}
            L = d.get("layer")
            if L is None:
                continue
            for k, v in d.get("tasks", {}).items():
                curves.setdefault(k, {})[str(L)] = v.get("acc")
        jdump(os.path.join(out_dir, "probe_acc.json"), {"curves": curves})
        print(f"[probe] 曲线 {len(curves)} 条 → probe_acc.json")


# --------------------------------------------------------------------------- #
# ③ ablation
# --------------------------------------------------------------------------- #
def generate_one(model, tok, row, args):
    msgs = [{"role": "system", "content": args.system_prompt},
            {"role": "user", "content": row["messages"][0]["content"]}]
    kw = dict(add_generation_prompt=True, tokenize=False)
    try:
        prompt = tok.apply_chat_template(msgs, enable_thinking=False, **kw)
    except Exception:
        prompt = tok.apply_chat_template(msgs, **kw)
    ids = tok(prompt, return_tensors="pt", add_special_tokens=False).input_ids.to("cuda:0")
    with torch.no_grad():
        out = model.generate(ids, max_new_tokens=args.max_new, do_sample=False,
                             pad_token_id=tok.pad_token_id or tok.eos_token_id)
    txt = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
    return txt, parse_tool_calls(txt), ids.shape[1]


def run_ablation(model, tok, bb, rows, labels, layer_ids, out_dir, args, judges):
    os.makedirs(os.path.join(out_dir, "ablation"), exist_ok=True)
    full_path = os.path.join(out_dir, "ablation", "layer_full.json")
    if not os.path.exists(full_path) or args.overwrite:
        recs = []
        t0 = time.time()
        for i, (_ln, row) in enumerate(rows):
            txt, calls, _ = generate_one(model, tok, row, args)
            ok = False
            if judges is not None:
                ok, why = judges.judge(row, txt, calls)
            recs.append({"prompt_id": i, "text": txt, "calls": len(calls), "pass": bool(ok)})
        jdump(full_path, {"layer": "full", "pass": sum(r["pass"] for r in recs),
                          "n": len(recs), "records": recs})
        print(f"[abl] full pass={sum(r['pass'] for r in recs)}/{len(recs)} "
              f"{time.time() - t0:.1f}s")
    full = jload(full_path) or {"records": [], "pass": 0, "n": len(rows)}

    layers = sorted(bb.layers)
    for L in layer_ids:
        dst = os.path.join(out_dir, "ablation", f"layer_{L:02d}.json")
        if os.path.exists(dst) and not args.overwrite:
            continue
        store = {}
        h = layers[L].register_forward_hook(make_zero_hook(L, store))
        recs = []
        t0 = time.time()
        try:
            for i, (_ln, row) in enumerate(rows):
                txt, calls, _ = generate_one(model, tok, row, args)
                ok = False
                if judges is not None:
                    ok, _ = judges.judge(row, txt, calls)
                ref = full["records"][i] if i < len(full["records"]) else {"text": "", "pass": False}
                recs.append({
                    "prompt_id": i, "text": txt, "calls": len(calls), "pass": bool(ok),
                    "top1_changed": (txt[:16] != ref.get("text", "")[:16]),
                    "sim_vs_full": round(text_similarity(txt, ref.get("text", "")), 4),
                })
        finally:
            h.remove()
        p = sum(r["pass"] for r in recs)
        jdump(dst, {"layer": L, "pass": p, "n": len(recs),
                    "delta_vs_full": p - full["pass"],
                    "top1_changed": sum(r["top1_changed"] for r in recs),
                    "mean_sim_vs_full": round(sum(r["sim_vs_full"] for r in recs) / max(1, len(recs)), 4),
                    "records": recs})
        print(f"[abl] L{L:02d} pass={p} Δ={p - full['pass']:+d} "
              f"top1_changed={sum(r['top1_changed'] for r in recs)}/{len(recs)} "
              f"{time.time() - t0:.1f}s")
    # merge
    if not os.path.exists(os.path.join(out_dir, "ablation.json")) or args.overwrite:
        out = {"full_pass": full["pass"], "n": full["n"], "layers": {}}
        for p in sorted(glob.glob(os.path.join(out_dir, "ablation", "layer_*.json"))):
            d = jload(p) or {}
            if isinstance(d.get("layer"), int):
                out["layers"][str(d["layer"])] = {k: d[k] for k in
                                                 ("pass", "delta_vs_full", "top1_changed",
                                                  "mean_sim_vs_full") if k in d}
        jdump(os.path.join(out_dir, "ablation.json"), out)
        print(f"[abl] 汇总 {len(out['layers'])} 层 → ablation.json")


# --------------------------------------------------------------------------- #
# ④ adapter layer energy (CPU only)
# --------------------------------------------------------------------------- #
def _spec_norm_power_iter(A, B, iters=30):
    """Largest singular value of B@A without materialising the [out,in] product."""
    import torch as T
    Af = A.float()
    Bf = B.float()
    v = T.randn(Af.shape[1], 1, dtype=T.float32)
    v /= v.norm() + 1e-12
    for _ in range(iters):
        u = Bf @ (Af @ v)
        n = u.norm()
        if n < 1e-20:
            return 0.0
        u /= n
        v = Af.t() @ (Bf.t() @ u)
        nv = v.norm()
        if nv < 1e-20:
            return 0.0
        v /= nv
    sigma = float(((Bf @ (Af @ v)).norm()))
    return sigma


def run_adapter(args, out_dir):
    from safetensors import safe_open
    st = os.path.join(args.adapter, "adapter_model.safetensors")
    if not os.path.exists(st):
        raise SystemExit(f"[FATAL] 缺 {st}")
    cfg = jload(os.path.join(args.adapter, "adapter_config.json"), {}) or {}
    r = int(cfg.get("r") or 16)
    alpha = int(cfg.get("lora_alpha") or 2 * r)
    scale = alpha / r
    pairs = {}
    with safe_open(st, framework="pt", device="cpu") as f:
        for k in f.keys():
            m = re.match(r"^(?:base_model\.model\.)?model\.layers\.(\d+)\.(.+)\.lora_([AB])\.weight$", k)
            if not m:
                continue
            pairs.setdefault((int(m.group(1)), m.group(2)), {})[m.group(3)] = f.get_tensor(k)
    per_layer = {}
    t0 = time.time()
    for (L, mod), d in sorted(pairs.items()):
        if "A" not in d or "B" not in d:
            continue
        A, B = d["A"], d["B"]
        fro_A = float(A.float().norm())
        fro_B = float(B.float().norm())
        # ||B@A||_F^2 = tr(A^T B^T B A) = sum((B^T B A) * A)
        M2 = B.float().t() @ B.float()
        fro_delta = float(((M2 @ A.float()) * A.float()).sum().clamp_min(0).sqrt())
        spec = _spec_norm_power_iter(A, B)
        rec = per_layer.setdefault(L, {"modules": {}, "fro_delta_sum": 0.0,
                                       "spec_max": 0.0, "spec_sum": 0.0, "n": 0})
        rec["modules"][mod] = {"fro_A": round(fro_A, 4), "fro_B": round(fro_B, 4),
                               "fro_delta": round(fro_delta, 4),
                               "fro_delta_scaled": round(fro_delta * scale, 4),
                               "spec_delta": round(spec, 4),
                               "spec_delta_scaled": round(spec * scale, 4)}
        rec["fro_delta_sum"] += fro_delta * scale
        rec["spec_max"] = max(rec["spec_max"], spec * scale)
        rec["spec_sum"] += spec * scale
        rec["n"] += 1
    for L, rec in per_layer.items():
        rec["fro_delta_sum"] = round(rec["fro_delta_sum"], 4)
        rec["spec_sum"] = round(rec["spec_sum"], 4)
        rec["spec_max"] = round(rec["spec_max"], 4)
    os.makedirs(out_dir, exist_ok=True)
    jdump(os.path.join(out_dir, "adapter_layer_norm.json"),
          {"adapter": os.path.abspath(args.adapter), "r": r, "alpha": alpha, "scale": scale,
           "layers": {str(k): v for k, v in sorted(per_layer.items())}})
    print(f"[adapter] {len(per_layer)} 层 / {sum(v['n'] for v in per_layer.values())} 模块 "
          f"{time.time() - t0:.1f}s → adapter_layer_norm.json")
    if per_layer:
        top = sorted(per_layer.items(), key=lambda kv: -kv[1]["spec_max"])[:6]
        print("[adapter] spec_max 前 6 层: " +
              ", ".join(f"L{L}={v['spec_max']:.3f}" for L, v in top))


# --------------------------------------------------------------------------- #
# dry run
# --------------------------------------------------------------------------- #
def _assistant_span(tok, msgs):
    """Token range [a, b) belonging to the final assistant turn.

    Uses the cumulative-prefix trick and verifies the prefix is an exact token
    prefix of the full sequence; on mismatch returns None instead of guessing.
    """
    try:
        pre = tok.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True)
        full = tok.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False)
    except Exception:
        return None
    if len(pre) >= len(full):
        return None
    return len(pre), len(full)


def _span_loss(model, input_ids, span, chunk=64):
    """Average CE over the assistant span only (token-chunked to bound VRAM)."""
    a, b = span
    with torch.no_grad():
        out = model(input_ids=input_ids, use_cache=False)
        logits = out.logits
    tot, n = 0.0, 0
    V = logits.shape[-1]
    for i in range(max(0, a - 1), max(0, b - 1), chunk):
        j = min(i + chunk, b - 1)
        if j <= i:
            break
        sl = logits[:, i:j, :].float()
        tgt = input_ids[:, i + 1:j + 1]
        tot += float(torch.nn.functional.cross_entropy(
            sl.reshape(-1, V), tgt.reshape(-1), reduction="sum"))
        n += j - i
    del logits
    return tot / max(1, n)


def _sensitive_span(curve, thr_mul=1.0):
    """Layers whose value > mean + thr_mul*std, as the longest contiguous run."""
    ks = sorted(int(k) for k in curve if curve[k] is not None)
    if not ks:
        return None
    import statistics
    vals = [curve[str(k)] for k in ks]
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals) or 1e-9
    thr = mu + thr_mul * sd
    runs, cur = [], []
    for k, v in zip(ks, vals):
        if v > thr:
            cur.append((k, v))
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return None
    best = max(runs, key=len)
    peak = max(best, key=lambda kv: kv[1])
    return [best[0][0], best[-1][0], peak[0], round(peak[1], 4), round(thr, 4)]


def _recommend(spans):
    """Map the per-category peaks onto the three §14.4 cases."""
    peaks = {c: s[2] for c, s in spans.items() if s}
    if len(peaks) < 2:
        return {"case": "insufficient", "why": f"只有 {len(peaks)} 类有敏感段，无法判断分离性"}
    vals = sorted(peaks.values())
    gaps = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
    detail = {c: p for c, p in peaks.items()}
    if all(g > 8 for g in gaps):
        return {"case": "separated", "why": "各类峰间距 > 8 层，可分段独立训练",
                "config": "A=[peak_re±4] r32 · B=[peak_route±4] r16 · C=[56,63] r8，数据 3:2:1",
                "peaks": detail}
    if vals[-1] - vals[0] <= 8:
        return {"case": "collapsed", "why": "各类峰集中在 ≤8 层内（多为后段），层无法切",
                "config": "单段训练，改用数据加权：逆向类 ×3–5，让 9.2% 升到 25–40%",
                "peaks": detail}
    return {"case": "two_groups", "why": f"峰间距 {gaps}，呈两组分布",
            "config": "A=[合并段] r32 · B=[56,63] r8，两类混合 1:1 再训纪律",
            "peaks": detail}


def run_probe_by_cat(args, model, tok, bb, layer_ids, out_dir):
    """Per-category layer curves (the §14.3 requirement).

    Two label sources, both computed here:
      A  weak label : assistant-span loss inside a category; below the category
         median = 1.  A well-fit sample means the model already represents it.
      B  ablation   : zero layer L's output and measure how much the same
         sample's loss rises -- a continuous sensitivity, not a binarisation.
    """
    import numpy as np
    cats = [c.strip() for c in args.cats.split(",") if c.strip()]
    rows_by_cat = {}
    with open(args.train_data, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            c = (r.get("meta") or {}).get("cat")
            if c in cats:
                rows_by_cat.setdefault(c, []).append(r)
    print("[cat] 候选: " + ", ".join(f"{c}={len(rows_by_cat.get(c, []))}" for c in cats))

    layers = list(bb.layers)
    ab_layers = parse_layers(args.ablate_layers, len(layers))
    ab_layers = [L for L in ab_layers if L in set(layer_ids)]
    rng = random.Random(args.seed)
    result = {"train_data": os.path.abspath(args.train_data), "cats": {},
              "ablation_dloss": {}, "sensitive_span": {}, "recommendation": None,
              "per_cat_samples": args.per_cat_samples, "per_cat_ablate": args.ablate_per_cat,
              "ablate_layers": ab_layers, "layers": layer_ids}

    tap = HiddenTap(layers, layer_ids, "cuda:0")
    t0 = time.time()
    for c in cats:
        pool = rows_by_cat.get(c, [])
        if len(pool) < 8:
            print(f"[cat][skip] {c} 只有 {len(pool)} 条")
            continue
        rng.shuffle(pool)
        sample = pool[:args.per_cat_samples]
        feats = {L: [] for L in layer_ids}
        losses, used = [], []
        for r in sample:
            msgs = r.get("messages") or []
            span = _assistant_span(tok, msgs)
            if span is None:
                continue
            try:
                text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            except Exception:
                continue
            ids = tok(text, add_special_tokens=False)["input_ids"][:args.ctx]
            if len(ids) < span[0] + 3:
                continue
            span = (span[0], min(span[1], len(ids)))
            input_ids = torch.tensor([ids], device="cuda:0")
            tap.reset()
            with torch.no_grad():
                model(input_ids=input_ids, use_cache=False)
            got = False
            for L in layer_ids:
                h = tap.caps.get(L)
                if h is None:
                    continue
                feats[L].append(h[:, -1, :].float().numpy()[0])
                got = True
            tap.caps = {}
            if not got:
                continue
            losses.append(_span_loss(model, input_ids, span, args.ce_chunk))
            used.append(r)
        if len(losses) < 6:
            print(f"[cat][skip] {c} 有效样本 {len(losses)} 太少")
            continue
        med = float(np.median(losses))
        y = np.array([1 if v < med else 0 for v in losses])
        base_acc = float(max(y.mean(), 1 - y.mean()))
        per_layer = {}
        for L in layer_ids:
            if len(feats[L]) != len(losses):
                continue
            X = np.stack(feats[L])
            r2, _impl = cv_accuracy(X, y, folds=min(5, max(2, int(np.bincount(y).min() or 2))))
            per_layer[str(L)] = None if r2 is None else round(r2[0], 4)
        result["cats"][c] = {
            "n": len(losses), "loss_median": round(med, 4),
            "loss_mean": round(float(np.mean(losses)), 4),
            "label_pos": int(y.sum()), "majority_acc": round(base_acc, 4),
            "probe_by_layer": per_layer,
        }
        best = max(((v or 0), int(k)) for k, v in per_layer.items())
        print(f"[cat] {c} n={len(losses)} median_loss={med:.3f} pos={int(y.sum())}/{len(y)} "
              f"majority={base_acc:.3f} best={best[0]:.3f}@L{best[1]} "
              f"({time.time() - t0:.0f}s)")

        # ---- ablation Δloss (continuous sensitivity) ------------------------
        ab_sample = sample[:args.ablate_per_cat]
        dloss = {}
        for L in ab_layers:
            store = {}
            hd = layers[L].register_forward_hook(make_zero_hook(L, store))
            ups = []
            try:
                for r in ab_sample:
                    msgs = r.get("messages") or []
                    span = _assistant_span(tok, msgs)
                    if span is None:
                        continue
                    try:
                        text = tok.apply_chat_template(msgs, tokenize=False,
                                                       add_generation_prompt=False)
                    except Exception:
                        continue
                    ids = tok(text, add_special_tokens=False)["input_ids"][:args.ctx]
                    if len(ids) < span[0] + 3:
                        continue
                    span = (span[0], min(span[1], len(ids)))
                    input_ids = torch.tensor([ids], device="cuda:0")
                    ups.append(_span_loss(model, input_ids, span, args.ce_chunk))
            finally:
                hd.remove()
            if ups:
                dloss[str(L)] = round(float(np.mean(ups)) - med, 4)
        result["ablation_dloss"][c] = dloss
        if dloss:
            top = sorted(dloss.items(), key=lambda kv: -kv[1])[:3]
            print(f"[cat] {c} Δloss 最敏感: " +
                  ", ".join(f"L{L}={v:+.3f}" for L, v in top))
    tap.close()

    for c, rec in result["cats"].items():
        sp = _sensitive_span(rec["probe_by_layer"])
        if sp:
            result["sensitive_span"][c] = sp
    # if the weak-label curve is flat, fall back to the Δloss curve
    for c, dl in result["ablation_dloss"].items():
        if c in result["sensitive_span"] or not dl:
            continue
        sp = _sensitive_span(dl, thr_mul=0.5)
        if sp:
            result["sensitive_span"][c] = sp
            result["cats"].setdefault(c, {})["span_source"] = "ablation_dloss"
    result["recommendation"] = _recommend(result["sensitive_span"])

    jdump(os.path.join(out_dir, "probe_by_cat.json"), result)
    print("[cat] sensitive_span: " +
          ", ".join(f"{c}={v[:3]}" for c, v in result["sensitive_span"].items()))
    print(f"[cat] recommendation: {result['recommendation']}")
    print(f"[cat] {time.time() - t0:.0f}s → probe_by_cat.json")
    return result


def merge_only(a):
    """Stitch per-layer json into the four summary files. No model load."""
    out = a.out
    merged = {}
    for p in glob.glob(os.path.join(out, "logit", "layer_*.json")):
        d = jload(p) or {}
        if isinstance(d.get("layer"), int):
            merged[d["layer"]] = d["prompts"]
    if merged:
        top_layer = max(merged)
        n = min(len(v) for v in merged.values())
        conv = {}
        for i in range(n):
            ref = merged[top_layer][i]["top5"][0][0]
            conv[i] = next((L for L in sorted(merged)
                            if merged[L][i]["top5"][0][0] == ref), None)
        vals = [v for v in conv.values() if v is not None]
        med = sorted(vals)[len(vals) // 2] if vals else None
        jdump(os.path.join(out, "logit_lens.json"),
              {"final_layer": top_layer, "convergence": conv,
               "convergence_median": med,
               "layers": {str(k): v for k, v in merged.items()}})
        print(f"[merge] logit_lens.json  {len(merged)} 层  收敛层 median={med}")
    curves = {}
    for p in sorted(glob.glob(os.path.join(out, "probe", "layer_*.json"))):
        d = jload(p) or {}
        L = d.get("layer")
        if L is None:
            continue
        for k, v in d.get("tasks", {}).items():
            curves.setdefault(k, {})[str(L)] = v.get("acc")
    if curves:
        jdump(os.path.join(out, "probe_acc.json"), {"curves": curves})
        print(f"[merge] probe_acc.json  {len(curves)} 条曲线")
    abl = {"full_pass": None, "n": None, "layers": {}}
    d = jload(os.path.join(out, "ablation", "layer_full.json"))
    if d:
        abl["full_pass"], abl["n"] = d.get("pass"), d.get("n")
    for p in sorted(glob.glob(os.path.join(out, "ablation", "layer_*.json"))):
        d = jload(p) or {}
        if isinstance(d.get("layer"), int):
            abl["layers"][str(d["layer"])] = {k: d.get(k) for k in
                                              ("pass", "delta_vs_full", "top1_changed",
                                               "mean_sim_vs_full")}
    if abl["layers"]:
        jdump(os.path.join(out, "ablation.json"), abl)
        print(f"[merge] ablation.json  {len(abl['layers'])} 层  full_pass={abl['full_pass']}")
    if os.path.exists(os.path.join(out, "adapter_layer_norm.json")):
        print("[merge] adapter_layer_norm.json 已存在")
    return 0


def dry_run(args):
    print("=== dry-run（CPU only，不加载权重） ===")
    from transformers import AutoConfig
    cfg = AutoConfig.from_pretrained(args.model, trust_remote_code=True)
    t = getattr(cfg, "text_config", cfg)
    n_layers = int(getattr(t, "num_hidden_layers", 64))
    hidden = int(getattr(t, "hidden_size", 0))
    vocab = int(getattr(t, "vocab_size", 0))
    print(f"[cfg] model_type={getattr(cfg,'model_type','?')} layers={n_layers} "
          f"hidden={hidden} vocab={vocab}")

    layers = parse_layers(args.layers, n_layers)
    print(f"[layers] {len(layers)} 个 → {layers[:8]}{'...' if len(layers) > 8 else ''}")

    rows = load_rows(args.data)
    print(f"[data] {len(rows)} 题  ({args.data})")
    lab = None
    if os.path.exists(args.labels):
        lab = (jload(args.labels) or {}).get("detail")
    if lab:
        assert len(lab) == len(rows), f"标签 {len(lab)} 条 vs 题目 {len(rows)} 条不匹配"
        cats = {}
        for d in lab:
            cats[d.get("cat")] = cats.get(d.get("cat"), 0) + 1
        print(f"[labels] pass={sum(1 for d in lab if d.get('pass'))}/{len(lab)}  "
              f"calls>0={sum(1 for d in lab if int(d.get('calls') or 0) > 0)}  cats={cats}")
    else:
        print(f"[labels][warn] 读不到 {args.labels} —— ② 与 ③ 的 pass 判据会退化")

    # hook contract on a CPU toy module
    class Toy(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.layers = torch.nn.ModuleList([torch.nn.Identity() for _ in range(4)])
            self.norm = torch.nn.Identity()

        def forward(self, x):
            for l in self.layers:
                x = l(x)
            return self.norm(x)

    m = Toy()
    tap = HiddenTap(m.layers, [1, 3], "cpu")
    x = torch.ones(1, 8, hidden, dtype=torch.bfloat16)   # non-zero so a zeroed output is provable
    y = m(x)
    assert set(tap.caps) == {1, 3}, tap.caps.keys()
    assert tap.caps[1].shape == (1, 8, hidden), tap.caps[1].shape
    assert tap.caps[1].dtype == torch.bfloat16
    tap.close()
    store = {}
    hd = m.layers[2].register_forward_hook(make_zero_hook(2, store))
    y2 = m(x)
    hd.remove()
    assert torch.count_nonzero(y) > 0, "基线输出应非零"
    assert torch.count_nonzero(y2) == 0, "置零 hook 未生效"
    print(f"[hook] ok  捕获 shape=(1,8,{hidden}) bf16 CPU 副本；置零 hook 生效（非零输入 → 0 输出）")

    per_prompt = args.ctx * hidden * 2                    # one layer, one prompt, bf16
    per_layer_feat = len(rows) * hidden * 4 * 2 + len(rows) * hidden * 2  # last+mean fp32, lasttok bf16
    print(f"[mem] 单题内 CPU 峰值 ≈ {human(per_prompt * len(layers))}"
          f"（{len(layers)} 层 × {human(per_prompt)}，每题目重置）"
          f" + 全量特征 ≈ {human(per_layer_feat * len(layers))}")
    print(f"[mem] 显存账：4bit 权重 12.6 GiB + KV≈1 GiB + head 反量化暂态 2.4 GiB ≈ 16 GiB（<20）")
    print(f"[plan] ① logit lens: {len(rows)} 题 × {len(layers)} 层，"
          f"每层一次 [1,1,{vocab}] 前向")
    print(f"[plan] ② probe: X=[{len(rows)},{hidden}] → 3 标签 × 2 pool × 5-fold")
    print(f"[plan] ③ ablation: {len(layers)} 层 × {len(rows)} 题 × max_new={args.max_new}")
    # per-category (§14.3): data availability + pure-python decision logic
    cats = [c.strip() for c in args.cats.split(",") if c.strip()]
    trows = load_rows(args.train_data) if os.path.exists(args.train_data) else []
    cnt = {}
    for _ln, r in trows:
        c = (r.get("meta") or {}).get("cat")
        if c in cats:
            cnt[c] = cnt.get(c, 0) + 1
    print(f"[cats] {os.path.basename(args.train_data)} {len(trows)} 行 → "
          + ", ".join(f"{c}={cnt.get(c, 0)}" for c in cats))
    ab_layers = [L for L in parse_layers(args.ablate_layers, n_layers) if L in set(layers)]
    print(f"[cats] 每类抽 {args.per_cat_samples} 条做弱标签，{args.ablate_per_cat} 条 × "
          f"{len(ab_layers)} 层做 Δloss")
    fake = {
        "kb-re": {str(i): (0.62 if 20 <= i <= 28 else 0.50) for i in range(n_layers)},
        "tool-route": {str(i): (0.58 if 40 <= i <= 50 else 0.50) for i in range(n_layers)},
        "real-discipline": {str(i): (0.60 if 56 <= i <= 63 else 0.50) for i in range(n_layers)},
    }
    spans = {c: _sensitive_span(cur) for c, cur in fake.items()}
    print(f"[span] 合成曲线自检 → { {c: (v[:3] if v else None) for c, v in spans.items()} }")
    print(f"[span] recommendation 自检 → {_recommend(spans)['case']}")

    print(f"[plan] ④ adapter: {args.adapter or '(未给 --adapter，跳过)'}")
    print(f"[out] {os.path.abspath(args.out)}")
    print("DRY_RUN_OK")
    return 0


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="layer-function probe for the 27B (logit lens / linear probe / ablation / adapter)")
    ap.add_argument("--model", default="/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B")
    ap.add_argument("--adapter", default="/root/autodl-tmp/kitty-rev/out/adapter")
    ap.add_argument("--data", default="/root/autodl-tmp/kitty-rev/kitty-rev/data/eval.jsonl")
    ap.add_argument("--labels", default="/root/autodl-tmp/kitty-rev/kitty-rev/logs/eval-baseline-20261020.json")
    ap.add_argument("--eval-dir", default="/root/autodl-tmp/kitty-rev/kitty-rev/eval")
    ap.add_argument("--out", default="/root/autodl-tmp/kitty-rev/probe-out")
    ap.add_argument("--mode", default="all", help="all | logit,probe,ablation,adapter | merge")
    ap.add_argument("--layers", default="all", help="all | 48-63 | 0,4,8")
    # --- per-category probing (§14.3) ---
    ap.add_argument("--train-data",
                    default="/root/autodl-tmp/kitty-rev/kitty-rev/data/large-mix/train.jsonl",
                    help="含 meta.cat 的 SFT 数据，用于按类别分层拟合")
    ap.add_argument("--cats", default="kb-re,action-reverse,tool-route,op-syntax,real-discipline")
    ap.add_argument("--per-cat-samples", type=int, default=40, help="每类抽样条数（弱标签）")
    ap.add_argument("--ablate-per-cat", type=int, default=8, help="每类消融 Δloss 的条数")
    ap.add_argument("--ablate-layers", default="0,8,16,24,32,40,44,48,52,56,60,63",
                    help="消融采样层（会与 --layers 取交集）")
    ap.add_argument("--ce-chunk", type=int, default=64, help="assistant loss 的 token 分块")
    ap.add_argument("--ctx", type=int, default=512)
    ap.add_argument("--max-new", type=int, default=256)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--overwrite", action="store_true", help="覆盖已有层结果（默认断点续跑）")
    ap.add_argument("--dry-run", action="store_true", help="CPU-only 自检，不加载权重")
    ap.add_argument("--no-text-only", action="store_true")
    ap.add_argument("--system-prompt", default="逆向工作台执行层。")
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    if a.dry_run:
        return dry_run(a)

    os.makedirs(a.out, exist_ok=True)
    modes = [m.strip() for m in a.mode.split(",") if m.strip()]
    if "all" in modes:
        modes = ["logit", "probe", "ablation", "adapter"]

    if modes == ["adapter"]:
        run_adapter(a, a.out)
        return 0
    if modes == ["merge"]:
        print("[merge] 只做汇总（复用已有 per-layer json，不加载模型）")
        return merge_only(a)

    model, tok, cfg = build_model(a)
    bb = backbone_of(model)
    t = getattr(cfg, "text_config", cfg)
    n_layers = len(bb.layers)
    hidden = int(getattr(t, "hidden_size", 0))
    layer_ids = parse_layers(a.layers, n_layers)
    print(f"[plan] layers={len(layer_ids)}/{n_layers} hidden={hidden} ctx={a.ctx} modes={modes}")

    rows = load_rows(a.data)
    label_detail = (jload(a.labels, {}) or {}).get("detail") if os.path.exists(a.labels) else None
    judges = load_eval_kitty(a.eval_dir)
    print(f"[plan] rows={len(rows)} labels={0 if not label_detail else len(label_detail)} "
          f"judges={'eval_kitty' if judges else '缺失'}")

    # ---- capture: one forward per prompt, keep last+mean pooled features ------
    if any(m in modes for m in ("logit", "probe")):
        import numpy as np
        tap = HiddenTap(list(bb.layers), layer_ids, "cuda:0")
        feats = {L: {"last": [], "mean": [], "lasttok": []} for L in layer_ids}
        t0 = time.time()
        for i, (_ln, row) in enumerate(rows):
            msgs = [{"role": "system", "content": a.system_prompt},
                    {"role": "user", "content": row["messages"][0]["content"]}]
            try:
                prompt = tok.apply_chat_template(msgs, tokenize=False,
                                                 add_generation_prompt=True,
                                                 enable_thinking=False)
            except Exception:
                prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
            ids = tok(prompt, return_tensors="pt", add_special_tokens=False).input_ids[:, :a.ctx].to("cuda:0")
            tap.reset()
            with torch.no_grad():
                model(input_ids=ids, use_cache=False)
            for L in layer_ids:
                h = tap.caps.get(L)
                if h is None:
                    continue
                feats[L]["last"].append(h[:, -1, :].float().numpy()[0])
                feats[L]["mean"].append(h.float().mean(dim=1).numpy()[0])
                feats[L]["lasttok"].append(h[:, -1:, :].to(torch.bfloat16).clone())
            tap.caps = {}
            if i == 0 or (i + 1) % 5 == 0:
                print(f"[fwd] {i + 1}/{len(rows)} "
                      f"vram={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB "
                      f"{(time.time() - t0) / (i + 1):.2f}s/题")
        tap.close()
        caps = {L: {"last": np.stack(feats[L]["last"]),
                    "mean": np.stack(feats[L]["mean"]),
                    "lasttok": feats[L]["lasttok"]} for L in layer_ids}
        nbytes = sum(v["last"].nbytes * 2 for v in caps.values())
        print(f"[fwd] done 特征 {human(nbytes)}（{'last+mean'} × {len(layer_ids)} 层）")

        if "logit" in modes:
            # ZERO extra forwards: the last-position hidden per layer was already
            # captured above, so the lens is just norm + lm_head on [1,1,H].
            # (An earlier version re-ran 23 prompts x 64 layers = 1472 forwards.)
            os.makedirs(os.path.join(a.out, "logit"), exist_ok=True)
            for L in layer_ids:
                dst = os.path.join(a.out, "logit", f"layer_{L:02d}.json")
                if os.path.exists(dst) and not a.overwrite:
                    continue
                per_prompt = []
                with torch.no_grad():
                    for i in range(len(rows)):
                        hl = caps[L]["lasttok"][i].to("cuda:0")     # [1,1,H]
                        hl = bb.norm(hl)
                        logits = model.lm_head(hl)[0, -1].float()
                        p = torch.softmax(logits, dim=-1)
                        top = torch.topk(p, 5)
                        per_prompt.append({"prompt_id": i,
                                           "top5": [[tok.decode([int(tv)], skip_special_tokens=True),
                                                     round(float(pv), 6)]
                                                    for tv, pv in zip(top.indices.tolist(),
                                                                      top.values.tolist())]})
                jdump(dst, {"layer": L, "n_prompts": len(rows), "prompts": per_prompt})
                print(f"[logit] L{L:02d} done")
            merged = {}
            for p in glob.glob(os.path.join(a.out, "logit", "layer_*.json")):
                d = jload(p) or {}
                if isinstance(d.get("layer"), int):
                    merged[d["layer"]] = d["prompts"]
            if merged:
                top_layer = max(merged)
                conv = {}
                for i in range(len(rows)):
                    ref = merged[top_layer][i]["top5"][0][0]
                    conv[i] = next((L for L in sorted(merged)
                                    if merged[L][i]["top5"][0][0] == ref), None)
                vals = [v for v in conv.values() if v is not None]
                jdump(os.path.join(a.out, "logit_lens.json"),
                      {"final_layer": top_layer, "convergence": conv,
                       "convergence_median": sorted(vals)[len(vals) // 2] if vals else None,
                       "layers": {str(k): v for k, v in merged.items()}})
                print(f"[logit] 收敛层 median="
                      f"{sorted(vals)[len(vals) // 2] if vals else None} → logit_lens.json")
        if "probe" in modes:
            run_probe(model, tok, bb, caps, rows, label_detail, layer_ids, a.out, a)

    if "ablation" in modes:
        run_ablation(model, tok, bb, rows, label_detail, layer_ids, a.out, a, judges)
    if "probecat" in modes:
        run_probe_by_cat(a, model, tok, bb, layer_ids, a.out)
    if "adapter" in modes:
        try:
            run_adapter(a, a.out)
        except SystemExit as e:
            print(f"[adapter][skip] {e}")
    print(f"[done] vram_peak={torch.cuda.max_memory_allocated() / 2 ** 30:.2f} GiB  out={a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
