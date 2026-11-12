#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""方案 Z 接管进度采样器：每 60s 写一次 train/lines/9b-oxcoder/out/z-progress.json
前台汇报只读这个文件 + train/logs/takeover-z.log 尾部，不碰训练进程。
"""
import json
import os
import re
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)

OUT = "train/lines/9b-oxcoder/out"
L = "train/logs"
PROG = os.path.join(OUT, "z-progress.json")
STAGES = os.path.join(L, "z-stages.md")
TK = os.path.join(L, "takeover-z.log")

STEP_RE = re.compile(r"(\d+)/(\d+)\s*\[")
LOSS_RE = re.compile(r"'loss':\s*'([0-9.eE+-]+)'")
LR_RE = re.compile(r"'learning_rate':\s*'([0-9.eE+-]+)'")


def tail_text(path, limit=400000):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit))
            return f.read()
    except Exception:
        return ""


def newest_log(paths):
    best, best_m = None, -1.0
    for p in paths:
        if os.path.isfile(p):
            m = os.path.getmtime(p)
            if m > best_m:
                best, best_m = p, m
    return best


JSONL_TOTALS = {"z-re": (6069, 2.13), "z-2a-v2": (864, 1.25), "z-2a": (288, 1.2)}


def parse_progress(path):
    if not path:
        return {}
    # ① jsonl（train-log.jsonl）：{"step":..,"loss":..}
    if path.endswith(".jsonl"):
        lines = [x for x in tail_text(path, 20000).strip().splitlines() if x.strip()]
        if lines:
            try:
                d0 = json.loads(lines[-1])
            except Exception:
                d0 = None
            if isinstance(d0, dict) and "step" in d0:
                total, sps = 0, 0.0
                flat = path.replace("\\", "/")
                for k in sorted(JSONL_TOTALS, key=len, reverse=True):
                    if k in flat:
                        total, sps = JSONL_TOTALS[k]
                        break
                cur = int(d0["step"])
                out = {
                    "cur": cur,
                    "total": total or 0,
                    "pct": round(100.0 * cur / total, 1) if total else 0.0,
                    "loss": round(float(d0.get("loss", 0.0)), 4),
                    "lr": f"{float(d0.get('learning_rate', 0.0)):.3g}",
                    "epoch": round(float(d0.get("epoch", 0.0)), 4),
                }
                if total and sps:
                    out["eta_min"] = round(sps * (total - cur) / 60.0, 1)
                return out
    # ② 进度条文本（night-z.log 等）
    txt = tail_text(path)
    ms = STEP_RE.findall(txt)
    if not ms:
        return {}
    cur, total = int(ms[-1][0]), int(ms[-1][1])
    d = {"cur": cur, "total": total, "pct": round(100.0 * cur / total, 1) if total else 0.0}
    losses = LOSS_RE.findall(txt)
    if losses:
        d["loss"] = float(losses[-1])
    lrs = LR_RE.findall(txt)
    if lrs:
        d["lr"] = lrs[-1]
    # ETA：用最近日志的 s/it
    it = re.findall(r"([0-9.]+)s/it", txt)
    if it and total > cur:
        d["eta_min"] = round(float(it[-1]) * (total - cur) / 60.0, 1)
    return d


def jload(p):
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def last_stage():
    try:
        lines = [x.strip() for x in open(STAGES, encoding="utf-8") if x.strip().startswith("|")]
    except Exception:
        return ""
    return lines[-1] if len(lines) > 2 else ""


def gate_rc(path):
    txt = tail_text(path, 20000)
    rc = re.findall(r"rc=(\d+)", txt)
    return int(rc[-1]) if rc else None


def main():
    while True:
        try:
            arts = {}
            for name, p in [
                ("zre_final", f"{OUT}/z-re/final"),
                ("2a_v1_final", f"{OUT}/z-2a/final"),
                ("2a_v2_final", f"{OUT}/z-2a-v2/final"),
                ("eval_re_zre", f"{OUT}/eval-re-zre.json"),
                ("eval_2a_z2a_v2", f"{OUT}/eval-2a-z2a-v2.json"),
                ("report", f"{L}/z-final-report.md"),
            ]:
                arts[name] = os.path.exists(p)

            info = {
                "ts": datetime.now().strftime("%F %T"),
                "stage": last_stage(),
                "artifacts": arts,
            }
            info["progress"] = parse_progress(
                newest_log([
                    f"{OUT}/z-2a-v2/train-log.jsonl",
                    f"{OUT}/z-re/train-log.jsonl",
                    f"{L}/z-2a-v2-train.log",
                    f"{L}/night-z.log",
                    TK,
                ])
            )

            re_j = jload(f"{OUT}/eval-re-zre.json")
            if isinstance(re_j, dict) and isinstance(re_j.get("results"), list):
                info["re_eval"] = [
                    {k: r.get(k) for k in ("label", "n", "hit", "acc", "fake", "wrong", "noarg")}
                    for r in re_j["results"]
                ]
            a2 = jload(f"{OUT}/eval-2a-z2a-v2.json")
            if isinstance(a2, dict):
                info["aa_eval"] = {
                    k: a2.get(k) for k in ("adapter", "n", "avg_cov", "code_rate", "avg_ngram20", "verdict")
                }
            base = jload(f"{OUT}/eval-2a-r3-v2.json")
            if isinstance(base, dict):
                info["aa_base"] = {k: base.get(k) for k in ("avg_cov", "code_rate")}
            info["gates"] = {
                "eval": gate_rc(f"{L}/gate-z2a-v2.log"),
                "toolname": gate_rc(f"{L}/gate-toolname-z2a.log"),
                "notool": gate_rc(f"{L}/gate-notool-z2a.log"),
            }
            # 最近事件
            tk = tail_text(TK, 8000).strip().splitlines()
            info["recent"] = tk[-4:] if tk else []

            tmp = PROG + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(info, f, ensure_ascii=False, indent=1)
            os.replace(tmp, PROG)
            with open(f"{L}/z-progress.log", "a", encoding="utf-8") as f:
                pr = info.get("progress") or {}
                f.write(f"[{info['ts']}] {info['stage']} "
                        f"{pr.get('cur','-')}/{pr.get('total','-')} "
                        f"loss={pr.get('loss','-')} eta={pr.get('eta_min','-')}m\n")
        except Exception as e:
            with open(f"{L}/z-progress.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%F %T}] ERR {e}\n")
        time.sleep(60)


if __name__ == "__main__":
    sys.exit(main())
