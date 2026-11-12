#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pick_checkpoint.py -- score the candidate adapters and pick one. Read-only.

Why not serve 3 times
    `serve_4bit_base.py` has no runtime adapter-swap endpoint, so the "three
    candidates" path would be: load (16 s) -> eval -> kill -> load -> ... for
    both the 60-item and 23-item suites.  This script loads the 4bit base ONCE
    per candidate with transformers and does everything in-process:
        * re-subset.val (72 rows) assistant-span loss   <- overfitting evidence
        * eval_re_extended (60)                          <- capability (primary)
        * eval_kitty (23)                                <- regression guard
    One 17.9 GiB residency at a time, never concurrent.  Files are written per
    candidate so a crash keeps finished results.

Judging reuses the real judges
    eval_re_extended.judge  (expect-rule driven)
    eval_kitty.judge        (RULES table)
    generation + tool-call parsing reuse serve_4bit_base.build_prompt /
    parse_tool_calls / strip_specials, so the text is scored exactly like a
    served answer.

Usage (cloud, after training finishes)
    python pick_checkpoint.py \
        --base-model base/Qwen3.8-27B \
        --candidates "245:out/checkpoint-245,490:out/checkpoint-490,full3ep:out/adapter-full3ep" \
        --re-eval kitty-rev/data/eval_re_extended.jsonl \
        --kitty-eval kitty-rev/data/eval.jsonl \
        --val-data kitty-rev/data/subsets/re-subset.val.jsonl \
        --out logs/pick

    python pick_checkpoint.py ... --dry-run     # check paths + suites, load nothing
"""
import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def jsonl(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


# val 文件的判读权重。forge-val 与 forge-train 是同一次生成后随机切分的
# （同 prompt 模板 / 同密度 / 同 cat 比例），所以它的 loss 偏乐观：能抓「背训练集」，
# 抓不住「过拟合模板」。re-val 来源不同（gold/silver 混合），权重给 2。
VAL_WEIGHT = {
    "re-subset.val.jsonl": 2.0,
    "forge-subset.val.jsonl": 1.0,
}

# 结果缓存（--out/<cand>.json）里的算法版本戳。
# 为什么必须带戳：dst 存在就"已有结果，跳过"——而 val_loss 的算法这轮才修过
# （lo 从 BatchEncoding 的字段数 2 改成真实前缀 token 数）。云端若留着上一轮的
# logs/pick/*.json，新跑会**静默复用旧 span_loss 的数字**去排名：报告一切正常，
# 选优结论却来自旧算法。带戳 + 不匹配就 FATAL，别让旧产物冒充新结果。
SPAN_SCHEME = "assistant_span_v2_tokprefix"


# 默认路径按脚本自身位置推导（= kitty-rev/），这样从仓库根或从 kitty-rev 里跑都对。
# 旧默认是 "kitty-rev/data/…"，只有从 kitty-rev 的父目录启动才成立；
# 配合新加的"文件缺失即 FATAL"，在别的目录直接跑会立刻报错（这是对的行为，但默认值别挖坑）。
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default(*parts):
    return os.path.join(BASE, *parts)


def _as_ids(x):
    """Token ids out of whatever `apply_chat_template(tokenize=True)` returned.

    Same trap as precompute_activations (defect #3): transformers 5.x returns a
    `BatchEncoding`, and `len(BatchEncoding)` is the number of FIELDS (2), not the
    number of tokens.  span_loss used `len(pre)` as the prompt-prefix length, so
    on re-subset.val row 0 it started the answer loss at token 2 instead of 69 --
    the system+user prompt and the template scaffolding were scored as if they
    were the answer.  Normalise first, always.
    """
    if hasattr(x, "input_ids"):
        return list(x.input_ids)
    if isinstance(x, (list, tuple)) and x and hasattr(x[0], "input_ids"):
        return list(x[0].input_ids)
    if isinstance(x, dict) and "input_ids" in x:
        return list(x["input_ids"])
    return list(x)


def _qhash(msgs):
    """问句指纹：只取非 assistant 侧内容（system+user）。"""
    parts = [str(m.get("content") or "") for m in msgs if m.get("role") != "assistant"]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def _ahash(msgs):
    """答案指纹：assistant 侧内容。"""
    parts = [str(m.get("content") or "") for m in msgs if m.get("role") == "assistant"]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def val_train_overlap(val_rows, train_rows):
    """val 里有多少条「与 train 同问」，其中多少条答案还不同。

    为什么值得一行：val_loss 是选优第三键，但它只在「val 是没见过的题」时才等于泛化。
    preflight 实测 re-train ∩ re-val = 10 条同问不同答（action-reverse 模板化生成：
    同一问句套给不同工具，gold 与 train 冲突）—— data 本身合规，但这 10 条会让
    val_loss 偏高，读者不知道就会把"val 也降了"当成泛化证据。
    返回 {"n", "same_q", "diff_a"}；train_rows 为空时返回 None（并让调用方 warn）。
    """
    if not train_rows:
        return None
    tmap = {}
    for r in train_rows:
        msgs = r.get("messages") or []
        tmap.setdefault(_qhash(msgs), set()).add(_ahash(msgs))
    same_q = diff_a = 0
    for r in val_rows:
        msgs = r.get("messages") or []
        q = _qhash(msgs)
        if q in tmap:
            same_q += 1
            if _ahash(msgs) not in tmap[q]:
                diff_a += 1
    return {"n": len(val_rows), "same_q": same_q, "diff_a": diff_a}


def span_bounds(tok, msgs, ctx):
    """(ids, lo, hi) of the assistant-answer span, or None if nothing is scorable.

    Split out of span_loss so scripts/regression/t12 can assert it with a fake
    tokenizer -- no GPU, no 27B weights.

    `lo` is a real token count (never `len(BatchEncoding)`), and it is additionally
    required to be an actual TOKEN prefix of `ids`: this chat template is only a
    character prefix at the assistant boundary (`<think>` vs `<think>\\n\\n` merge
    differently in BPE), so a pre rendered with add_generation_prompt=True can
    disagree with the full render.  When they disagree we clamp to the longest
    common prefix instead of silently scoring the scaffolding as the answer.
    """
    pre = _as_ids(tok.apply_chat_template(msgs[:-1], tokenize=True,
                                          add_generation_prompt=True))
    full = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
    ids = _as_ids(tok(full, add_special_tokens=False))[:ctx]
    lo = len(pre)
    hi = min(len(ids), ctx)
    if ids[:lo] != pre:
        k = 0
        while k < min(len(pre), len(ids)) and pre[k] == ids[k]:
            k += 1
        lo = k
    if hi - lo < 2:
        return None
    return ids, lo, hi


def main():
    ap = argparse.ArgumentParser(description="score candidate checkpoints, pick the best")
    ap.add_argument("--base-model", default="base/Qwen3.8-27B")
    ap.add_argument("--candidates",
                    default="245:out/checkpoint-245,490:out/checkpoint-490,"
                            "full3ep:out/adapter-full3ep")
    ap.add_argument("--re-eval", default=_default("data", "eval_re_extended.jsonl"))
    ap.add_argument("--kitty-eval", default=_default("data", "eval.jsonl"))
    ap.add_argument("--val-data", default=_default("data", "subsets", "re-subset.val.jsonl"),
                    help="过拟合证据集，可逗号分隔多个文件（如 re-subset.val.jsonl,"
                         "forge-subset.val.jsonl）。forge 不进这里 → 候选把 forge 背下来也看不出来")
    ap.add_argument("--out", default="logs/pick")
    # 4096：带 kit_mod.SYS(229字) + 4 个 tools 时 prompt 实测 618-669 tok，
    # 512 会把 prompt 截成断头（截掉 user 尾部/SYS 尾部），模型转而「续写残句」，
    # 实测输出 8 tok/28 字符 → 判据全灭。见 logs/cloud-full-watch.log 的 E1/E1b 对照。
    ap.add_argument("--ctx", type=int, default=4096)
    # 哪些评测集带 tools。re_eval 的判据要散文（min_chars 60 + required_any 关键词），
    # 带 tools 时模型一律输出 tool_call，散文判据永远打不到 → re 默认不带。
    ap.add_argument("--tools-for", default="kitty",
                    help="逗号分隔：re,kitty（默认 kitty；re 带 tools 会只出 tool_call）")
    ap.add_argument("--max-new", type=int, default=512)
    ap.add_argument("--val-limit", type=int, default=0, help="只算前 N 条 val（0=全部 72）")
    ap.add_argument("--limit", type=int, default=0, help="每套题只跑前 N 条（调试）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="忽略 --out 里的旧结果并强制重算（旧算法产物 span_scheme 不匹配时必须用）")
    ap.add_argument("--train-data", default="",
                    help="训练侧 jsonl（逗号分隔，可空）。只有给了才能核对 val 与 train 的"
                         "同问重叠 —— 同问不同答会让 val_loss 偏高，读者得知道")
    a = ap.parse_args()
    tools_for = {x.strip() for x in (a.tools_for or "").split(",") if x.strip()}
    print(f"[口径] ctx={a.ctx}  max_new={a.max_new}  tools_for={sorted(tools_for) or 'none'}")

    cands = []
    for part in a.candidates.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise SystemExit(f"[FATAL] --candidates 需 name:path，得到 {part!r}")
        name, path = part.split(":", 1)
        cands.append((name.strip(), path.strip()))

    # 与 --val-data 同一条规矩：路径打错不许退化成"0 题"。
    # 旧写法下 --re-eval 打错 → re_rows=[] → 能力主判据消失，报告仍然打 PASS/FAIL。
    def _load_suite(path, label):
        if not os.path.exists(path):
            raise SystemExit(f"[FATAL] {label} 文件不存在: {path}")
        rows = jsonl(path)
        if not rows:
            raise SystemExit(f"[FATAL] {label} 文件是空的: {path}")
        return rows

    re_rows = _load_suite(a.re_eval, "--re-eval")
    kit_rows = _load_suite(a.kitty_eval, "--kitty-eval")
    # 多文件拼接；任何一个列出来的文件缺失或 0 行 → FATAL。
    # 旧写法 `if os.path.exists(...) else []` 会把打错的路径变成"没有 val 证据"，
    # 排序键里 val_loss=None 只是排到最后，报告里只显示 "-"，没有任何报错。
    # --val-limit 按文件各取前 N（合并后再截断会让后面的类永远评不到）。
    val_rows, val_by_file, val_groups = [], {}, []
    for vp in [x.strip() for x in a.val_data.split(",") if x.strip()]:
        if not os.path.exists(vp):
            raise SystemExit(f"[FATAL] --val-data 里的文件不存在: {vp}")
        rows_v = jsonl(vp)
        if not rows_v:
            raise SystemExit(f"[FATAL] --val-data 文件是空的: {vp}")
        if a.val_limit:
            rows_v = rows_v[:a.val_limit]
        val_by_file[os.path.basename(vp)] = len(rows_v)
        val_groups.append((os.path.basename(vp), rows_v))
        val_rows.extend(rows_v)
    if a.limit:
        re_rows, kit_rows = re_rows[:a.limit], kit_rows[:a.limit]
    # --val-limit 已在逐文件读取时应用（见上）

    print(f"[plan] base={a.base_model}")
    print(f"[plan] 评测集: re_extended={len(re_rows)}  kitty={len(kit_rows)}  "
          f"val={len(val_rows)}  {val_by_file}")

    # val ↔ train 同问重叠：只有给了 --train-data 才核得出来，没给就明说"不知道"，
    # 不许让读者以为 val_loss 一定是泛化证据（第 21 例）。
    train_rows = []
    if a.train_data:
        for tp in [x.strip() for x in a.train_data.split(",") if x.strip()]:
            if not os.path.exists(tp):
                raise SystemExit(f"[FATAL] --train-data 里的文件不存在: {tp}")
            train_rows.extend(jsonl(tp))
        if not train_rows:
            raise SystemExit("[FATAL] --train-data 读进来是 0 行")
    else:
        print("[warn] 未给 --train-data：核对不了 val 与 train 的同问重叠，"
              "val_loss 的可信度未知（同问不同答会把它抬高）")
    val_overlap_by_file = {}
    for fname, rows_v in val_groups:
        ov = val_train_overlap(rows_v, train_rows)
        if ov is None:
            continue
        val_overlap_by_file[fname] = ov
        flag = "⚠ 同问不同答" if ov["diff_a"] else "✓"
        print(f"[plan] val {fname:26s} 与 train 同问 {ov['same_q']:3d}/{ov['n']:<3d} 条"
              f"（答案不同 {ov['diff_a']:3d}）{flag}")

    for name, path in cands:
        ok = os.path.isdir(path)
        n = len([f for f in os.listdir(path) if f.endswith(".safetensors")]) if ok else 0
        print(f"[cand] {name:10s} {path}  {'✓ ' + str(n) + ' safetensors' if ok else '✗ 不存在'}")
    if a.dry_run:
        print("[dry-run] 未加载模型、未评测")
        return 0

    here = os.path.dirname(os.path.abspath(__file__))
    # 重依赖**延迟**到真的要算的时候（见 ensure_stack）：
    # 旧代码在候选循环之前就 import torch + transformers，于是「同戳复用缓存」
    # 这条路径也硬依赖训练栈 —— 在只有 CPU 的机器上，缓存守卫（span_scheme
    # FATAL / --refresh）**永远走不到**，回归集 t20 只能靠 ImportError 拿到 rc=1，
    # 语义断言全是空过。判据不可达 = 判据不存在。
    _loaded = {"ok": False}

    def ensure_stack():
        if _loaded["ok"]:
            return
        global re_mod, kit_mod, serve, torch
        global AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        re_mod = load_mod(os.path.join(here, "eval_re_extended.py"), "re_ext")
        kit_mod = load_mod(os.path.join(os.path.dirname(here), "eval", "eval_kitty.py"),
                           "kit_ext")
        serve = load_mod(os.path.join(here, "serve_4bit_base.py"), "serve_mod")
        import torch as _torch
        from transformers import (AutoModelForCausalLM as _AM, AutoTokenizer as _AT,
                                  BitsAndBytesConfig as _BQ)
        torch, AutoModelForCausalLM = _torch, _AM
        AutoTokenizer, BitsAndBytesConfig = _AT, _BQ
        _loaded["ok"] = True

    results = {}
    for name, path in cands:
        dst = os.path.join(a.out, f"{name}.json")
        if os.path.exists(dst) and a.refresh:
            print(f"[{name}] --refresh：忽略旧结果 {dst}")
        elif os.path.exists(dst):
            rec_old = json.load(open(dst, encoding="utf-8"))
            got = rec_old.get("span_scheme")
            if got != SPAN_SCHEME:
                # 旧产物不许冒充新结果：val_loss 的算法换过（lo 从 2 改成真实前缀长度），
                # 拿旧 json 排名 = 用旧算法选 checkpoint，而报告看不出任何异常。
                raise SystemExit(
                    f"[FATAL] {dst} 是旧算法产物（span_scheme={got!r}，当前 {SPAN_SCHEME!r}）。\n"
                    f"        它的 val_loss 与当前不可比，不能参与排名。\n"
                    f"        处理：删掉该文件重跑，或加 --refresh 强制重算。")
            results[name] = rec_old
            print(f"[{name}] 已有结果，跳过（{dst}  span_scheme={got}）")
            continue
        if not os.path.isdir(path):
            print(f"[{name}][skip] adapter 目录不存在：{path}")
            continue
        ensure_stack()          # 到这里才真正需要 torch/transformers

        print(f"\n=== [{name}] 加载 {a.base_model} + {path}（4bit）===")
        t0 = time.time()
        bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                 bnb_4bit_compute_dtype=torch.bfloat16,
                                 bnb_4bit_use_double_quant=True)
        tok = AutoTokenizer.from_pretrained(a.base_model, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            a.base_model, quantization_config=bnb, device_map={"": 0},
            dtype=torch.bfloat16, trust_remote_code=True)
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, path)
        model.eval()
        if tok.pad_token_id is None:
            tok.pad_token_id = tok.eos_token_id
        print(f"[{name}] load {time.time() - t0:.1f}s  "
              f"vram={torch.cuda.memory_allocated() / 2 ** 30:.2f} GiB")

        def gen(msgs, tools):
            p = serve.build_prompt(tok, msgs, tools, False, "medium")
            ids = tok(p, return_tensors="pt", add_special_tokens=False).input_ids[:, :a.ctx].cuda()
            with torch.no_grad():
                out = model.generate(ids, max_new_tokens=a.max_new, do_sample=False,
                                     pad_token_id=tok.pad_token_id,
                                     eos_token_id=tok.eos_token_id)
            txt = serve.strip_specials(tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))
            return txt, serve.parse_tool_calls(txt)

        def span_loss(msgs):
            # 旧写法：lo = len(pre)，而 pre 是 BatchEncoding → lo = 字段数(2)，
            # 答案 loss 从 token 2 开始算，把 system+user prompt 与模板脚手架
            # 全算成答案（实测 lo=2 / 真实 69 / T=134）。见 span_bounds()。
            b = span_bounds(tok, msgs, a.ctx)
            if b is None:
                return None
            ids, lo, hi = b
            tid = torch.tensor([ids], device="cuda:0")
            with torch.no_grad():
                lg = model(input_ids=tid, use_cache=False).logits
            tot, n = 0.0, 0
            V = lg.shape[-1]
            for i in range(max(0, lo - 1), max(0, hi - 1), 64):
                j = min(i + 64, hi - 1)
                if j <= i:
                    break
                sl = lg[:, i:j, :].float()
                tgt = tid[:, i + 1:j + 1]
                tot += float(torch.nn.functional.cross_entropy(
                    sl.reshape(-1, V), tgt.reshape(-1), reduction="sum"))
                n += j - i
            del lg
            return tot / max(1, n)

        rec = {"candidate": name, "adapter": os.path.abspath(path),
               "span_scheme": SPAN_SCHEME,   # 旧产物没有这行 → 不可比，见 SPAN_SCHEME 注释
               "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if val_overlap_by_file:
            rec["val_train_overlap"] = val_overlap_by_file

        # 1) val loss —— 按文件分开算，再按 VAL_WEIGHT 合成
        #    forge-val 与 forge-train 同源同分布 → loss 偏乐观，权重 1
        #    re-val 来源不同（gold/silver 混合）→ 权重 2，判读时以它为准
        t1 = time.time()
        vls_by_file, n_by_file, n_skip_by_file = {}, {}, {}
        for fname, rows_v in val_groups:
            vs, n_skip, first_err = [], 0, None
            for row in rows_v:
                try:
                    v = span_loss(row.get("messages") or [])
                except Exception as e:      # 模板/编码异常 → 记数+报一次，不吞
                    n_skip += 1
                    first_err = first_err or f"{type(e).__name__}: {e}"
                    continue
                if v is None:
                    n_skip += 1
                    continue
                vs.append(v)
            if n_skip:
                n_skip_by_file[fname] = n_skip
                print(f"[{name}][warn] val {fname}: {n_skip}/{len(rows_v)} 条无可算答案 span"
                      f"（消息不足 / 超 --ctx 截断 / 模板前缀漂移到 0）→ 未计入 loss")
                if first_err:
                    print(f"[{name}][warn] 首个异常：{first_err}")
            if not vs:
                # 旧写法这里只打 n=0，loss 显示 "-"，整个选优维度消失而报告正常。
                print(f"[{name}][warn] val {fname}: 0 条可算 → 该文件对 val_loss 完全无贡献")
                continue
            vls_by_file[fname] = round(sum(vs) / len(vs), 4)
            n_by_file[fname] = len(vs)
            print(f"[{name}] val {fname:26s} n={len(vs):3d} "
                  f"loss={vls_by_file.get(fname)}  {time.time() - t1:.0f}s")
        rec["val_loss_by_file"] = vls_by_file
        rec["val_n_by_file"] = n_by_file
        if n_skip_by_file:
            rec["val_n_skipped_by_file"] = n_skip_by_file
        wsum = sum(VAL_WEIGHT.get(k, 1.0) for k in vls_by_file)
        if wsum:
            rec["val_loss"] = round(
                sum(v * VAL_WEIGHT.get(k, 1.0) for k, v in vls_by_file.items()) / wsum, 4)
            rec["val_weights"] = {k: VAL_WEIGHT.get(k, 1.0) for k in vls_by_file}
        else:
            rec["val_loss"] = None
        rec["val_files"] = val_by_file
        print(f"[{name}] val_loss(加权)={rec['val_loss']}  "
              f"weights={rec.get('val_weights')}  {time.time() - t1:.0f}s")

        # 2) eval_re_extended 60
        t2 = time.time()
        rdet, rp = [], 0
        for i, row in enumerate(re_rows, 1):
            user = row["messages"][0]["content"]
            txt, calls = gen([{"role": "system", "content": kit_mod.SYS},
                              {"role": "user", "content": user}],
                             kit_mod.TOOLS if "re" in tools_for else None)
            ok, why = re_mod.judge(row, txt, calls)
            rp += ok
            rdet.append({"i": i, "cat": (row.get("meta") or {}).get("cat"),
                         "pass": bool(ok), "why": why})
            if i % 15 == 0:
                print(f"[{name}] re {i}/{len(re_rows)} pass={rp}  {time.time() - t2:.0f}s")
        rec["re_pass"], rec["re_total"] = rp, len(re_rows)
        rec["re_detail"] = rdet
        print(f"[{name}] eval_re_extended {rp}/{len(re_rows)}  {time.time() - t2:.0f}s")

        # 3) eval_kitty 23
        t3 = time.time()
        kdet, kp = [], 0
        for i, row in enumerate(kit_rows, 1):
            user = row["messages"][0]["content"]
            txt, calls = gen([{"role": "system", "content": kit_mod.SYS},
                              {"role": "user", "content": user}],
                             kit_mod.TOOLS if "kitty" in tools_for else None)
            ok, why = kit_mod.judge(row, txt, calls)
            kp += ok
            kdet.append({"i": i, "cat": (row.get("meta") or {}).get("cat"),
                         "pass": bool(ok), "why": why})
        rec["kitty_pass"], rec["kitty_total"] = kp, len(kit_rows)
        rec["kitty_detail"] = kdet
        print(f"[{name}] eval_kitty {kp}/{len(kit_rows)}  {time.time() - t3:.0f}s")

        os.makedirs(a.out, exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=2)
        print(f"[{name}] → {dst}")
        results[name] = rec

        # 注意：del model 后 PyTorch 仍可能保留数 GiB reserved（实测 4.99 GiB），
        # 下一个候选在 caching_allocator_warmup 里申请 11 GiB 会 OOM（实测 00:37）。
        # 多候选务必：① 分进程跑，或 ② 设置 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
        # 并在此处 torch.cuda.empty_cache() + 校验 reserved 归零。
        del model
        torch.cuda.empty_cache()

    # ---- ranking -----------------------------------------------------------
    def score(r):
        # capability first, then regression, then lower val loss
        # val_loss 用**显式 None** 判断：`(r.get("val_loss") or 99)` 会把合法的 0.0
        # 也当成缺失（0.0 是 falsy）——那样"loss 极低"的候选反而被排到最后。
        vl = r.get("val_loss")
        return (r.get("re_pass", 0), r.get("kitty_pass", 0),
                -(vl if vl is not None else 99))

    ranked = sorted([r for r in results.values() if "re_pass" in r], key=score, reverse=True)

    def vf(r, f, w=8):
        v = (r.get("val_loss_by_file") or {}).get(f)
        return f"{v:.4f}".rjust(w) if v is not None else "-".rjust(w)

    print("\n" + "=" * 96)
    print(f"{'candidate':12s} {'eval_re(60)':>12s} {'eval_kitty(23)':>15s} "
          f"{'re_val':>8s} {'forge_val':>9s} {'val_wtd':>8s}  notes")
    order = {"245": "epoch1", "490": "epoch2", "full3ep": "epoch3"}
    for r in [results[k] for k in order if k in results] + \
             [v for k, v in results.items() if k not in order]:
        print(f"{r['candidate']:12s} {r.get('re_pass', '-')!s:>6}/{r.get('re_total', '-'):<5} "
              f"{r.get('kitty_pass', '-')!s:>8}/{r.get('kitty_total', '-'):<5} "
              f"{vf(r, 're-subset.val.jsonl')} {vf(r, 'forge-subset.val.jsonl', 9)} "
              f"{str(r.get('val_loss', '-')):>8}  {order.get(r['candidate'], '')}")
    print("  权重：re-val 2.0 / forge-val 1.0（forge-val 与 forge-train 同源同分布，判读以 re-val 为准）")
    if ranked:
        best = ranked[0]
        mono = [results[k].get("re_pass") for k in ("245", "490", "full3ep") if k in results]
        decay = len(mono) >= 2 and all(mono[i] >= mono[i + 1] for i in range(len(mono) - 1))
        why = (f"re={best['re_pass']}/{best['re_total']} kitty={best['kitty_pass']}/"
               f"{best['kitty_total']} re_val={vf(best, 're-subset.val.jsonl').strip()} "
               f"forge_val={vf(best, 'forge-subset.val.jsonl').strip()}")
        if decay:
            why += "；三个候选分数单调递减 → 后两 epoch 过拟合，选早期 checkpoint"
        print(f"\n推荐: {best['candidate']}   理由: {why}")
    print("=" * 78)
    with open(os.path.join(a.out, "_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"ranking": [r["candidate"] for r in ranked],
                   "best": ranked[0]["candidate"] if ranked else None,
                   "table": {k: {kk: r.get(kk) for kk in
                                 ("re_pass", "re_total", "kitty_pass", "kitty_total",
                                  "val_loss", "val_loss_by_file", "val_weights")}
                             for k, r in results.items()},
                   "val_weights": VAL_WEIGHT}, f, ensure_ascii=False, indent=2)
    print(f"[done] 汇总 → {os.path.join(a.out, '_summary.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
