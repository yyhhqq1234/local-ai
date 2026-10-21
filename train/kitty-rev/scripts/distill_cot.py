#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""distill_cot.py —— 前沿模型思维链蒸馏（教师 → 训练数据）

用途：把 Opus5.5 / GPT6Astra / Grok4.7 / DSV4Pro / K3 的**完整推理链**跑在我们的任务提示上，
      落成可训练样本（学生=本地 27B IQ2）。

用法:
  python distill_cot.py --probe --all               # 逐路由探活（不花 token）
  python distill_cot.py --probe                     # 只探 enabled=true 的路由
  python distill_cot.py --gen --route dsv4pro --seeds data/reasoning/seeds.jsonl --out data/distill/dsv4pro.jsonl --limit 200
  python distill_cot.py --gen --routes all --seeds ... --out data/distill/ --sleep 1.2
  python distill_cot.py --stats data/distill/dsv4pro.jsonl
  python distill_cot.py --merge --dir data/distill --out data/reasoning/distilled.jsonl --max-tokens 1500

设计要点:
  · 只依赖系统 curl（本机 Python urllib 到外部 HTTPS 有 40s 级慢路径）
  · 抓 reasoning_content / reasoning / thinking / reasoning_details 四种字段
  · 每条样本带完整 provenance（teacher/model/promptId/ts/hasReasoning/estTokens）
  · 过滤：拒答模板、超长、纯空、与 seeds 重复；--merge 时统一截到 token 上限
  · 断点续跑：out 已存在的 promptId 跳过

合规提醒：蒸馏数据只用于自有模型内部训练；产出模型不得声称具备教师模型能力。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
ROUTES = os.path.join(HERE, "distill", "routes.json")
CJK = re.compile(r"[\u4e00-\u9fa5]")
REFUSAL = re.compile(r"(抱歉|无法协助|不能提供|I can't help|I cannot assist|作为(一个)?AI)")


def est_tokens(t):
    c = len(CJK.findall(t))
    return int(c + (len(t) - c) * 0.27)


def load_routes(path=ROUTES):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def curl(args, timeout=180, data_path=None):
    cmd = ["curl", "-sS", "-m", str(timeout)] + args
    if data_path:
        cmd += ["--data-binary", "@" + data_path]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def key_of(route):
    env = route.get("api_key_env") or ""
    return os.environ.get(env, "") if env else ""


# ---------------------------------------------------------------- probe
def cmd_probe(a):
    doc = load_routes()
    rows = []
    for rt in doc["routes"]:
        if not a.all and not rt.get("enabled"):
            continue
        key = key_of(rt)
        base = rt["base_url"].rstrip("/")
        if not key:
            rows.append((rt["id"], "NO-KEY", f"环境变量 {rt.get('api_key_env') or '-'} 未设置"))
            continue
        if rt.get("compat") == "anthropic":
            rc, out, err = curl(["-o", "/dev/null", "-w", "%{http_code}", "-H", f"x-api-key: {key}",
                                 "-H", "anthropic-version: 2023-06-01", base + "/models"])
        else:
            rc, out, err = curl(["-o", "/dev/null", "-w", "%{http_code}", "-H", f"Authorization: Bearer {key}",
                                 base + "/models"])
        code = (out or "").strip()
        verdict = {"200": "OK", "401": "BAD-KEY", "403": "FORBIDDEN", "404": "NO-ENDPOINT"}.get(code, f"HTTP{code}")
        rows.append((rt["id"], verdict, f"{base}/models → {code} {err[:80]}"))
    print(f"{'route':14s} {'verdict':12s} detail")
    for r in rows:
        print(f"{r[0]:14s} {r[1]:12s} {r[2]}")
    ok = sum(1 for r in rows if r[1] == "OK")
    print(f"\n[probe] 可用 {ok}/{len(rows)}")
    return 0


# ---------------------------------------------------------------- gen
def build_payload(rt, prompt, max_tokens, want_reasoning):
    if rt.get("compat") == "anthropic":
        body = {"model": rt["model"], "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if want_reasoning:
            body["thinking"] = {"type": "enabled", "budget_tokens": min(8000, max(1024, max_tokens // 2))}
        return body
    body = {"model": rt["model"], "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "stream": False}
    if want_reasoning:
        body["reasoning"] = {"effort": "high"}
    return body


def pick_reasoning(msg):
    for k in ("reasoning_content", "reasoning", "thinking", "reasoning_details"):
        v = msg.get(k)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, list):
            txt = "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in v)
            if txt.strip():
                return txt
    return ""


def cmd_gen(a):
    doc = load_routes()
    routes = [r for r in doc["routes"] if (r["id"] in a.route or a.routes == "all") and (r.get("enabled") or a.force)]
    if not routes:
        print("[FATAL] 没有匹配的路由（检查 --route / enabled / --force）")
        return 2

    seeds = []
    with open(a.seeds, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            prompt = d.get("prompt") or (d.get("messages") or [{}])[0].get("content")
            if prompt:
                seeds.append({"id": d.get("id") or hashlib.sha1(prompt.encode()).hexdigest()[:12],
                              "prompt": prompt, "meta": d.get("meta", {})})
    if a.limit:
        seeds = seeds[:a.limit]
    print(f"[gen] routes={[r['id'] for r in routes]} seeds={len(seeds)} maxTokens={a.max_tokens}")

    out_dir = a.out
    if a.routes == "all":
        os.makedirs(out_dir, exist_ok=True)

    for rt in routes:
        key = key_of(rt)
        if not key and rt.get("api_key_env"):
            print(f"[skip] {rt['id']}: 缺 {rt['api_key_env']}")
            continue
        path = os.path.join(out_dir, f"{rt['id']}.jsonl") if a.routes == "all" else out_dir
        done = set()
        if a.resume and os.path.isfile(path):
            for line in open(path, encoding="utf-8"):
                try:
                    done.add(json.loads(line)["meta"]["promptId"])
                except Exception:
                    pass
        base = rt["base_url"].rstrip("/")
        kept = 0
        with open(path, "a" if a.resume else "w", encoding="utf-8") as f:
            for s in seeds:
                if s["id"] in done:
                    continue
                payload = build_payload(rt, s["prompt"], a.max_tokens, a.want_reasoning)
                tmp = os.path.join(os.path.dirname(os.path.abspath(path)), "_payload.json")
                with open(tmp, "w", encoding="utf-8") as pf:
                    json.dump(payload, pf, ensure_ascii=False)
                if rt.get("compat") == "anthropic":
                    url = base + "/messages"
                    hdr = ["-H", f"x-api-key: {key}", "-H", "anthropic-version: 2023-06-01"]
                    rc, out, err = curl(hdr + ["-H", "content-type: application/json", "-X", "POST", url], data_path=tmp)
                else:
                    url = base + "/chat/completions"
                    hdr = (["-H", f"Authorization: Bearer {key}"] if key else []) + ["-H", "content-type: application/json"]
                    rc, out, err = curl(hdr + ["-X", "POST", url], data_path=tmp)
                if rc != 0 or not out.strip():
                    print(f"  [{rt['id']}] {s['id']} rc={rc} err={err[:80]}")
                    continue
                try:
                    j = json.loads(out)
                except json.JSONDecodeError:
                    print(f"  [{rt['id']}] {s['id']} 非 JSON 回包：{out[:80]}")
                    continue
                if rt.get("compat") == "anthropic":
                    blocks = j.get("content") or []
                    think = "\n".join(b.get("thinking", "") for b in blocks if isinstance(b, dict) and b.get("type") == "thinking")
                    text = "\n".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
                else:
                    msg = ((j.get("choices") or [{}])[0].get("message") or {})
                    think = pick_reasoning(msg)
                    text = msg.get("content") or ""
                if not text.strip():
                    continue
                if REFUSAL.search(text[:200]) and not think:
                    continue
                full = (think + "\n" + text).strip()
                rec = {"messages": ([{"role": "system", "content": s["prompt"].split("\n")[0][:200]}] if False else [])
                       + [{"role": "user", "content": s["prompt"]},
                          {"role": "assistant", "content": full}],
                       "meta": {"cat": "distilled", "tier": "teacher",
                                "teacher": rt["id"], "model": rt["model"],
                                "promptId": s["id"], "ts": int(time.time()),
                                "hasReasoning": bool(think), "estTokens": est_tokens(full),
                                "seedMeta": s.get("meta", {})}}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                kept += 1
                if kept % 10 == 0:
                    print(f"  [{rt['id']}] kept={kept}")
                time.sleep(a.sleep)
        print(f"[ok] {rt['id']} → {path} kept={kept}")
    return 0


# ---------------------------------------------------------------- stats / merge
def cmd_stats(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    toks = sorted(r["meta"].get("estTokens", 0) for r in rows)
    hr = sum(1 for r in rows if r["meta"].get("hasReasoning"))
    print(json.dumps({"file": path, "rows": len(rows), "withReasoning": hr,
                      "reasoningRate": round(hr / max(1, len(rows)), 3),
                      "estTokens": {"p50": toks[len(toks) // 2] if toks else 0,
                                    "p90": toks[int(len(toks) * 0.9)] if toks else 0,
                                    "max": toks[-1] if toks else 0}}, ensure_ascii=False, indent=2))
    return 0


def cmd_merge(a):
    files = []
    for name in sorted(os.listdir(a.dir)):
        if name.endswith(".jsonl"):
            files.append(os.path.join(a.dir, name))
    out, seen, kept = [], set(), 0
    for p in files:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            msgs = r["messages"]
            key = (msgs[0]["content"][:100], r["meta"].get("teacher"))
            if key in seen:
                continue
            seen.add(key)
            est = r["meta"].get("estTokens", 0)
            if est > a.max_tokens:
                if not a.truncate:
                    continue
                asst = msgs[-1]["content"]
                ratio = a.max_tokens / max(1, est)
                keep = int(len(asst) * ratio)
                msgs[-1]["content"] = asst[: int(keep * 0.65)] + "\n…（中段已省略）…\n" + asst[-int(keep * 0.35):]
            r["meta"]["cat"] = "reasoning"
            r["meta"]["tier"] = "teacher"
            out.append(r)
            kept += 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[ok] merge → {a.out}: kept={kept} from files={len(files)}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--all", action="store_true", help="probe 时连 disabled 路由一起探")
    ap.add_argument("--gen", action="store_true")
    ap.add_argument("--route", nargs="*", default=[])
    ap.add_argument("--routes", choices=["one", "all"], default="one")
    ap.add_argument("--force", action="store_true", help="无视 enabled=false")
    ap.add_argument("--seeds", default=os.path.join(DATA, "reasoning", "seeds.jsonl"))
    ap.add_argument("--out", default=os.path.join(DATA, "distill"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--want-reasoning", dest="want_reasoning", action="store_true", default=True)
    ap.add_argument("--stats", default="")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--dir", default=os.path.join(DATA, "distill"))
    ap.add_argument("--truncate", action="store_true")
    a = ap.parse_args()

    if a.probe:
        return cmd_probe(a)
    if a.stats:
        return cmd_stats(a.stats)
    if a.merge:
        return cmd_merge(a)
    if a.gen:
        return cmd_gen(a)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
