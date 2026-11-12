#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_reasoning.py —— 抓开源推理链数据（免依赖：走 HF datasets-server rows API）

用法:
  python fetch_reasoning.py --list
  python fetch_reasoning.py --dataset open-thoughts/OpenThoughts-114k --limit 4000 --out data/reasoning/openthoughts-4k.jsonl
  python fetch_reasoning.py --stats data/reasoning/openthoughts-4k.jsonl
  python fetch_reasoning.py --dataset GAIR/LIMO --out data/reasoning/limo.jsonl --max-tokens 1500

设计:
  · 不装 datasets / huggingface_hub；只依赖 urllib
  · 先 /splits 探 config+split，再用 /rows 分页拉（单次 ≤100 行）
  · 统一归一成 {"messages":[user,assistant], "meta":{...}}，与主训练集同构
  · --stats：token 分布 / 重复率 / 与自有 eval 的污染检查
  · 断点续抓：已写行数 = offset 起点（--resume）

许可提醒：Apache-2.0 / CC-BY-4.0 可训练可分发；蒸馏型只做小比例抽样。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
DS = "https://datasets-server.huggingface.co"
CJK = re.compile(r"[\u4e00-\u9fa5]")
UA = {"User-Agent": "kitty-rev-dataset-fetcher/1.0"}

REGISTRY = [
    # (id, 说明, 许可, 建议抽样)
    ("open-thoughts/OpenThoughts-114k", "通用推理链（数学/代码/科学，R1 生成）", "Apache-2.0", "4000"),
    ("open-thoughts/OpenThoughts3-1.2M", "大体量通用推理链", "Apache-2.0", "3000"),
    ("bespokelabs/Bespoke-Stratos-17k", "带自我修正结构的推理链", "Apache-2.0", "3000"),
    ("GAIR/LIMO", "817 条精选，证少而精有效", "Apache-2.0", "817"),
    ("simplescaling/s1K", "1k 精选推理链", "Apache-2.0", "1000"),
    ("open-r1/OpenR1-Math-220k", "数学 R1 轨迹（含 verify）", "Apache-2.0", "4000"),
    ("AI-MO/NuminaMath-CoT", "数学 CoT 基础盘（较短）", "Apache-2.0", "3000"),
    ("AI-MO/NuminaMath-TIR", "工具集成推理（TIR）", "Apache-2.0", "3000"),
    ("nvidia/OpenMathReasoning", "多解数学推理（大体量）", "CC-BY-4.0", "2000"),
    ("nvidia/OpenCodeReasoning", "代码解题推理链", "CC-BY-4.0", "3000"),
    ("nvidia/OpenCodeReasoning-2", "代码推理二代", "CC-BY-4.0", "2000"),
    ("open-r1/codeforces-cots", "竞赛题推理链", "Apache-2.0", "2000"),
    ("Team-ACE/ToolACE", "工具定义+调用链", "Apache-2.0", "2000"),
    ("Salesforce/xlam-function-calling-60k", "函数调用合集", "CC-BY-4.0", "2000"),
    ("Magpie-Align/Magpie-Pro-300K-Filtered", "通用指令（防退化，少量）", "Apache-2.0", "1000"),
    ("a-m-team/AM-DeepSeek-R1-Distilled-1.4M", "全蒸馏（只小比例抽样）", "见卡片", "1000"),
]

USER_KEYS = ("question", "problem", "input", "query", "prompt", "instruction", "text")
ASST_KEYS = ("solution", "answer", "output", "response", "completion", "generated_solution", "reasoning")


def _curl_json(url, timeout=30):
    """用系统 curl 取 JSON：本机 Python urllib 走 datasets-server 要 42s（TLS/IPv6 慢路径），curl 0.7s。"""
    import subprocess
    for exe in ("curl", "curl.exe"):
        try:
            r = subprocess.run([exe, "-sS", "-m", str(timeout), "-H", "User-Agent: kitty-rev/1.0", url],
                               capture_output=True, timeout=timeout + 5)
            if r.returncode == 0 and r.stdout.strip():
                return json.loads(r.stdout.decode("utf-8", "replace"))
            if r.returncode != 0:
                raise RuntimeError(f"curl rc={r.returncode} {r.stderr[:120]!r}")
        except FileNotFoundError:
            continue
    return None


def http_json(url, retries=3):
    for i in range(retries):
        try:
            d = _curl_json(url)
            if d is not None:
                return d
            raise RuntimeError("empty response")
        except Exception as e:
            if i == retries - 1:
                print(f"[warn] http_json 失败：{e}")
                return None
            time.sleep(1.0 * (i + 1))
    return None


def resolve_splits(dsid):
    # 注意：dataset id 里的 "/" 不能编码成 %2F，datasets-server 会拒
    q = "dataset=" + urllib.parse.quote(dsid, safe="/")
    d = http_json(f"{DS}/splits?{q}")
    splits = (d or {}).get("splits") or []
    if not splits:
        return None
    pref = [s for s in splits if s.get("split") == "train"] or splits
    s = pref[0]
    return s.get("config"), s.get("split")


def normalize(row, dsid):
    """把各种字段布局归一成 user/assistant。"""
    if not isinstance(row, dict):
        return None
    conv = row.get("conversations") or row.get("messages")
    if isinstance(conv, list) and conv:
        u = a = None
        for m in conv:
            role = str(m.get("from") or m.get("role") or "").lower()
            val = m.get("value") or m.get("content") or ""
            if isinstance(val, list):
                val = "\n".join(str(x.get("text", "")) for x in val if isinstance(x, dict))
            if role in ("user", "human") and u is None:
                u = str(val)
            elif role in ("assistant", "gpt", "bot") and a is None:
                a = str(val)
        if u and a:
            return u, a, row.get("system")
    u = next((str(row[k]) for k in USER_KEYS if isinstance(row.get(k), str) and row[k].strip()), None)
    a = next((str(row[k]) for k in ASST_KEYS if isinstance(row.get(k), str) and row[k].strip()), None)
    if u and a:
        return u, a, row.get("system")
    return None


def est_tokens(t):
    c = len(CJK.findall(t))
    return int(c + (len(t) - c) * 0.27)


def headtail(asst, budget_tokens):
    """长 CoT 截断：保头 60% + 尾 40%，中间打省略标记（保留结论与起手，去掉中段冗余）。"""
    if est_tokens(asst) <= budget_tokens:
        return asst, False
    cjk = len(CJK.findall(asst))
    ratio = budget_tokens / max(1, est_tokens(asst))
    keep_chars = int(len(asst) * ratio)
    head = int(keep_chars * 0.6)
    tail = max(0, keep_chars - head)
    return asst[:head] + "\n…（中段已省略）…\n" + (asst[-tail:] if tail else ""), True


def cmd_list():
    print(f"{'HF id':52s} {'建议抽样':>8s}  许可            说明")
    for dsid, desc, lic, rec in REGISTRY:
        print(f"{dsid:52s} {rec:>8s}  {lic:15s} {desc}")
    print("\n拉取示例：python fetch_reasoning.py --dataset GAIR/LIMO --out data/reasoning/limo.jsonl")


def cmd_fetch(a):
    cfg, split = (a.config, a.split) if a.config and a.split else resolve_splits(a.dataset)
    if not cfg or not split:
        print(f"[FATAL] 无法解析 config/split：{a.dataset}（用 --config/--split 显式指定）")
        return 2
    print(f"[info] {a.dataset} config={cfg} split={split} limit={a.limit} maxTokens={a.max_tokens}")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    start = 0
    if a.resume and os.path.isfile(a.out):
        with open(a.out, "r", encoding="utf-8") as f:
            start = sum(1 for _ in f)
        print(f"[info] resume from offset={start}")

    kept = skipped_long = skipped_bad = truncated = 0
    seen = set()
    with open(a.out, "a" if a.resume else "w", encoding="utf-8") as f:
        offset = start
        while kept < a.limit:
            batch = min(100, a.limit - kept)
            q = ("dataset=" + urllib.parse.quote(a.dataset, safe="/") +
                 "&config=" + urllib.parse.quote(cfg, safe="/") +
                 "&split=" + urllib.parse.quote(split, safe="/") +
                 f"&offset={offset}&length={batch}")
            try:
                d = http_json(f"{DS}/rows?{q}")
            except Exception as e:
                print(f"[warn] rows 请求失败 offset={offset}: {e}")
                break
            rows = (d or {}).get("rows") or []
            if not rows:
                break
            for item in rows:
                norm = normalize(item.get("row") or {}, a.dataset)
                if not norm:
                    skipped_bad += 1
                    continue
                u, asst, sysmsg = norm
                full = u + "\n" + asst
                if est_tokens(full) > a.max_tokens:
                    if a.truncate == "drop":
                        skipped_long += 1
                        continue
                    asst, _ = headtail(asst, max(200, a.max_tokens - est_tokens(u) - 50))
                    full = u + "\n" + asst
                    truncated += 1
                h = hashlib.sha1((u[:200] + asst[:200]).encode("utf-8")).hexdigest()
                if h in seen:
                    continue
                seen.add(h)
                msgs = ([{"role": "system", "content": sysmsg}] if sysmsg and len(sysmsg) < 2000 else []) + \
                       [{"role": "user", "content": u}, {"role": "assistant", "content": asst}]
                rec = {"messages": msgs,
                       "meta": {"cat": "reasoning", "tier": "reasoning", "src": a.dataset,
                                "split": split, "offset": item.get("row_idx"), "estTokens": est_tokens(full)}}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                kept += 1
                if kept >= a.limit:
                    break
            offset += len(rows)
            print(f"  offset={offset} kept={kept} skip_long={skipped_long} skip_bad={skipped_bad} truncated={truncated}")
            if len(rows) < batch:
                break
    print(f"[ok] {a.out}: kept={kept} skip_long={skipped_long} skip_bad={skipped_bad} truncated={truncated}")
    return 0


def cmd_stats(path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    toks = sorted(r["meta"].get("estTokens") or est_tokens("".join(m["content"] for m in r["messages"]))
                  for r in rows)
    users = [r["messages"][0]["content"][:40] for r in rows if r.get("messages")]
    uniq = len(set(users))
    ev_path = os.path.join(DATA, "large", "eval.jsonl")
    ev = set()
    if os.path.isfile(ev_path):
        for line in open(ev_path, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    ev.add(json.loads(line)["messages"][0]["content"][:40])
                except Exception:
                    pass
    contam = len(set(users) & ev) if ev else -1
    print(json.dumps({
        "file": path, "rows": len(rows),
        "estTokens": {"min": toks[0] if toks else 0, "p50": toks[len(toks) // 2] if toks else 0,
                      "p90": toks[int(len(toks) * 0.9)] if toks else 0, "max": toks[-1] if toks else 0},
        "unique_prompt_prefix40": uniq, "dup_rate": round(1 - uniq / max(1, len(rows)), 4),
        "eval_contamination": contam,
    }, ensure_ascii=False, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dataset", default="")
    ap.add_argument("--config", default="")
    ap.add_argument("--split", default="")
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--out", default="")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--truncate", choices=["drop", "headtail"], default="drop",
                    help="超 token 上限的样本：drop=丢弃 / headtail=保头尾截断")
    ap.add_argument("--stats", default="")
    a = ap.parse_args()

    if a.list:
        cmd_list()
        return 0
    if a.stats:
        return cmd_stats(a.stats)
    if not a.dataset or not a.out:
        ap.print_help()
        return 1
    return cmd_fetch(a)


if __name__ == "__main__":
    sys.exit(main())
