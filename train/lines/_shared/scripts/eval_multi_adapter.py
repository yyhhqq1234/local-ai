"""多档 adapter 对比 —— 单次加载，循环 set_adapter

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
为什么改
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
原来跑 4 档对比要起 4 个进程、各加载一次基座（每次 ≈1.5 分钟），纯等待 6 分钟。
改成：加载基座一次 → 把所有 LoRA 挂上去（每个只有 173 MB）→ 循环 set_adapter。

省掉的只是「加载基座」的时间，评测逻辑不变，结果应与逐进程版一致。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  python eval_multi_adapter.py \
    --adapters "基座=,档1=train/lines/9b-oxcoder/out/re-stage1-fixed/final,档2=train/lines/9b-oxcoder/out/re-r2-ckpt1400-snapshot"

  标签=路径，用逗号分隔；路径留空 = 基座（不挂 LoRA）
  --out 汇总 JSON；--cases N 只跑前 N 条
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import argparse
import json
import os
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
BASE_TAG = None   # None=原版基座（保持历史缓存键不变）；--base 覆写时置为目录名
GIB = 2 ** 30


def load_base():
    # ★ 防系统卡顿：显存硬上限 + CPU 线程限制 + BelowNormal 优先级
    import gpu_guard; gpu_guard.apply()
    from transformers import AutoModelForImageTextToText, AutoTokenizer, BitsAndBytesConfig

    bnb = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForImageTextToText.from_pretrained(
        BASE, device_map={"": 0}, low_cpu_mem_usage=True,
        attn_implementation="sdpa", quantization_config=bnb,
    )
    for p in model.parameters():
        if p.dtype == torch.float32:
            p.data = p.data.to(torch.bfloat16)
    model.eval()
    inner = getattr(model, "model", None)
    if inner is not None and getattr(inner, "visual", None) is not None:
        inner.visual = None
        torch.cuda.empty_cache()
    print("[load] 基座 allocated = %.2f GiB" % (torch.cuda.memory_allocated() / GIB))
    return model, tok


def attach_adapters(model, specs):
    """specs: [(label, path)]；挂上所有 adapter，返回 name→label 映射"""
    from peft import PeftModel

    name2label = {}
    with_lora = [(lb, p) for lb, p in specs if p]
    if not with_lora:
        return model, name2label

    first_lb, first_p = with_lora[0]
    model = PeftModel.from_pretrained(model, first_p, adapter_name="a0")
    name2label["a0"] = first_lb
    for i, (lb, p) in enumerate(with_lora[1:], 1):
        model.load_adapter(p, adapter_name="a%d" % i)
        name2label["a%d" % i] = lb
    model.eval()
    print("[load] 已挂 %d 个 adapter：%s"
          % (len(with_lora), ", ".join(name2label.values())))
    return model, name2label


CACHE_DIR = os.path.join(_L9B, "out", "eval-cache")


def _file_md5(path, n=1 << 20):
    """只读前 1MB 算 md5 —— 足够区分 adapter，比读全量快"""
    import hashlib
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            h.update(f.read(n))
    except Exception:
        return "nofile"
    return h.hexdigest()[:12]


CACHE_VER = "v2"   # ★ detail 结构变更就递增：v1 只记工具名，v2 起记 resp 原文+参数约束


def cache_key(adapter_path, specs_all, cases, max_new):
    """缓存键 = 缓存结构版本 + 场景库内容 + max_new + 该档 adapter 指纹（基座档用 'base'）

    场景库变了 / 生成上限变了 / adapter 变了 / **detail 结构变了**，键就变，不会误命中。
    （v1 的缓存里没有 resp 原文，命中后拿不到参数诊断 → 必须换键）
    """
    import hashlib
    cases_digest = hashlib.md5(
        "|".join("%s:%s" % (c["id"], c["ask"]) for c in cases).encode()
    ).hexdigest()[:10]
    if not adapter_path:
        fp = "base"
    else:
        fp = _file_md5(os.path.join(adapter_path, "adapter_model.safetensors"))
    btag = "" if BASE_TAG is None else "-" + BASE_TAG
    return "%s-%s%s-%s-%d" % (CACHE_VER, cases_digest, btag, fp, max_new)


def cache_get(k):
    import json
    p = os.path.join(CACHE_DIR, k + ".json")
    if os.path.isfile(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return None
    return None


def cache_put(k, data):
    import json
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, k + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def main():
    global BASE, BASE_TAG
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapters", required=True,
                    help="标签=路径，逗号分隔；路径留空=基座。例：基座=,档1=/path/a,档2=/path/b")
    ap.add_argument("--base", default=None,
                    help="基座目录（默认 models/OxCoder-9B）。SRA 系 adapter **必须**显式指定 SRA 基座，"
                         "否则会把 LoRA 挂到错误权重上，结果无意义")
    ap.add_argument("--cases", type=int, default=0, help="只跑前 N 条（0=全部 40）")
    ap.add_argument("--max-new", type=int, default=300,
                    help="生成上限。**不为了提速压低**——压低会截断参数，制造假 noarg")
    ap.add_argument("--batch", type=int, default=1,
                    help="批量生成条数。**默认 1（逐条）** —— 2026-10-28 实测 batch=4/8 "
                         "均会改变评测结果（3/36、1/8 关键信息不同），虽快 2-3 倍但不可用。"
                         "仅用于实验，勿用于基线")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.base:
        BASE = args.base
        BASE_TAG = os.path.basename(os.path.normpath(BASE))
        print("[base] 覆写基座 → %s（cache tag=%s）" % (BASE, BASE_TAG))
        if not os.path.isdir(BASE):
            sys.exit("[FATAL] 基座目录不存在：%s" % BASE)

    specs = []
    for item in args.adapters.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            lb, p = item.split("=", 1)
            specs.append((lb.strip(), p.strip()))
        else:
            specs.append((item, ""))
    if not specs:
        sys.exit("[FATAL] --adapters 为空")

    from eval_cases_re import CASES
    from eval_re_generalize import load_system
    from toolname import load_tools, extract

    tools = load_tools()
    SYSTEM = load_system()
    cases = CASES[:args.cases] if args.cases else CASES

    print("=" * 80)
    print("多档 adapter 对比 —— %d 档 × %d 条场景（单次加载 · batch=%d）"
      % (len(specs), len(cases), args.batch))
    print("=" * 80)

    model, tok = load_base()
    model, name2label = attach_adapters(model, specs)

    # 基座档（path 为空的）不挂 adapter，评测时把 adapter 关掉
    base_labels = {lb for lb, p in specs if not p}

    # ★ 提速唯一不降质量的手段：批量生成（逐条 vs 批量，贪婪解码结果应逐字一致）
    #   注意三个要点：
    #   1) 生成必须左 padding（tok.padding_side = "left"），否则右侧 pad 会被当成正文
    #   2) pad_token_id 要与 tokenizer 的 pad 一致，避免生成乱码
    #   3) max_new 不动 —— 压低上限会截断参数，制造假的 noarg（参数错）
    tok.padding_side = "left"
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token

    def _mk_text(users):
        return [tok.apply_chat_template(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": u}],
            tokenize=False, add_generation_prompt=True) for u in users]

    @torch.inference_mode()
    def ask_batch(users):
        texts = _mk_text(users)
        enc = tok(texts, return_tensors="pt", padding=True,
                  add_special_tokens=False).to(model.device)
        prompt_len = enc["input_ids"].shape[1]
        out = model.generate(
            **enc, max_new_tokens=args.max_new, do_sample=False,
            temperature=None, top_p=None,
            pad_token_id=tok.pad_token_id,
        )
        return [tok.decode(out[i][prompt_len:], skip_special_tokens=True)
                for i in range(len(users))]

    def ask(user):
        return ask_batch([user])[0]

    # 预热：第一次 generate 含 CUDA kernel 首次编译（约 5-10 s），先跑一条短的空转
    try:
        ask_batch(["预热"])
        print("[warmup] 完成（约 5-10 s，省掉首次 generate 的 kernel 编译开销）")
    except Exception as e:
        print("[warmup] 跳过: %s" % e)

    def evaluate(label, adapter_path=""):
        ck = cache_key(adapter_path, specs, cases, args.max_new)
        cached = cache_get(ck)
        if cached:
            print("  [cache] 命中 %s（adapter 指纹 + 场景库 + max_new 一致）" % ck)
            return cached
        hit = wrong = fake = none = noarg = 0
        by_lv = {}
        detail = []
        B = max(1, args.batch)
        resps = []
        for i in range(0, len(cases), B):
            resps.extend(ask_batch([c["ask"] for c in cases[i:i + B]]))

        for c, resp in zip(cases, resps):
            # 统一走 eval_re_generalize.classify（六分类，含参数判定与负向题）
            from eval_re_generalize import classify as _classify
            kind, got, missing, fk = _classify(resp, c["expect"], c.get("args"))
            if kind == "hit":
                hit += 1
            elif kind == "noarg":
                noarg += 1
            elif kind == "wrong":
                wrong += 1
            elif kind == "fake":
                fake += 1
            else:
                none += 1
            lv = by_lv.setdefault(c["level"], {"hit": 0, "n": 0})
            lv["n"] += 1
            if kind == "hit":
                lv["hit"] += 1
            # ★ 参数诊断字段（CACHE_VER=v2 起）：resp 原文 + 参数约束 + 缺项
            #   只有 kind 而无原文时，无法知道 noarg 到底错在哪个参数值上，
            #   也就无法反推该造什么样的补强数据。
            detail.append({"id": c["id"], "kind": kind,
                           "got": sorted(got)[:4], "fake": sorted(fk),
                           "expect": sorted(c["expect"]),
                           "level": c["level"], "note": c.get("note", ""),
                           "expect_args": c.get("args") or {},
                           "missing": missing,
                           "resp": (resp or "").strip()[:600]})
        n = len(cases)
        out = {"label": label, "n": n, "hit": hit, "noarg": noarg,
               "wrong": wrong, "fake": fake, "none": none,
               "acc": round(hit / n, 4), "by_level": by_lv, "detail": detail}
        cache_put(ck, out)
        print("  [cache] 写入 %s" % ck)
        return out

    results = []
    # 先跑不挂 adapter 的档（基座）：用 PeftModel 的 disable_adapter 上下文
    if base_labels:
        for lb in base_labels:
            print()
            print("──────── %s（基座，adapter 已禁用）────────" % lb)
            try:
                with model.disable_adapter():
                    r = evaluate(lb, "")
            except AttributeError:
                # 没挂任何 LoRA（全是基座档）时 disable_adapter 不存在
                r = evaluate(lb, "")
            r["level_str"] = "%d/%d/%d" % (r["by_level"].get("L1", {}).get("hit", 0),
                                           r["by_level"].get("L2", {}).get("hit", 0),
                                           r["by_level"].get("L3", {}).get("hit", 0))
            results.append(r)
            print("  命中 %d/%d (%.1f%%) | 参数错 %d | 选错 %d | 编造 %d | 回避 %d | L1/L2/L3=%s"
                  % (r["hit"], r["n"], r["acc"] * 100, r["noarg"],
                     r["wrong"], r["fake"], r["none"], r["level_str"]))

    # 再跑挂了 adapter 的档
    # with_lora 在 attach_adapters 里是局部变量，这里重建一份
    _with_lora = [(lb, p) for lb, p in specs if p]
    name2path = {("a%d" % i): p for i, (lb, p) in enumerate(_with_lora)}
    for name, lb in name2label.items():
        spec_path = name2path.get(name, "")
        if hasattr(model, "set_adapter"):
            model.set_adapter(name)
        print()
        print("──────── %s（adapter %s）────────" % (lb, name))
        r = evaluate(lb, spec_path)
        r["level_str"] = "%d/%d/%d" % (r["by_level"].get("L1", {}).get("hit", 0),
                                       r["by_level"].get("L2", {}).get("hit", 0),
                                       r["by_level"].get("L3", {}).get("hit", 0))
        results.append(r)
        print("  命中 %d/%d (%.1f%%) | 参数错 %d | 选错 %d | 编造 %d | 回避 %d | L1/L2/L3=%s"
              % (r["hit"], r["n"], r["acc"] * 100, r["noarg"],
                 r["wrong"], r["fake"], r["none"], r["level_str"]))

    print()
    print("=" * 80)
    print("汇总")
    print("=" * 80)
    print("%-14s %-9s %-8s %-6s %-6s %-6s %-10s"
          % ("档", "命中率", "参数错", "选错", "编造", "回避", "L1/L2/L3"))
    for r in results:
        print("%-14s %-9s %-8d %-6d %-6d %-6d %-10s"
              % (r["label"], "%.1f%%" % (r["acc"] * 100),
                 r["noarg"], r["wrong"], r["fake"], r["none"], r["level_str"]))

    out = args.out or os.path.join(_L9B, "out", "eval-multi-adapter.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"cases_per_adapter": len(cases), "results": results},
                  f, ensure_ascii=False, indent=2)
    print()
    print("  明细 → %s" % out)


if __name__ == "__main__":
    main()
