#!/usr/bin/env python
"""
rebuild_eval_traj.py — 重建 val/test 的轨迹集（按 uuid 去重，不靠 offset）

问题：Nemotron 的 streaming 顺序不稳定，用 offset 切分导致 test 与训练集重叠 285/379。
修复：先收集训练集全部 uuid 作黑名单，生成时跳过；不依赖 offset 的稳定性。
"""
from __future__ import annotations
import argparse, itertools, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "train" / "data"
EVAL = DATA / "eval"
NEMOTRON = "nvidia/Nemotron-SWE-v1"

TRAIN_TRAJ = [
    DATA / "agent-traj" / "nemotron-swe" / "swe-8k.jsonl",
    DATA / "agent-traj" / "nemotron-swe" / "swe-16k.jsonl",
]


def load_blacklist():
    """训练集里已用过的 uuid（只读）"""
    used = set()
    for p in TRAIN_TRAJ:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            u = (o.get("meta") or {}).get("uuid")
            if u:
                used.add(u)
    return used


def render_traj(msgs):
    out = []
    for m in msgs:
        r = m.get("role")
        if r == "assistant":
            parts = []
            if (m.get("content") or "").strip():
                parts.append(m["content"].strip())
            for c in (m.get("tool_calls") or []):
                fn = c.get("function") or {}
                a = fn.get("arguments")
                if isinstance(a, (dict, list)):
                    a = json.dumps(a, ensure_ascii=False)
                parts.append(f"[CALL {fn.get('name','tool')}] {a or ''}")
            if parts:
                out.append("【assistant】" + "\n".join(parts))
        elif r == "tool":
            if (m.get("content") or "").strip():
                out.append("【observation】" + m["content"].strip())
    return "\n\n".join(out)


def clip(text, tok, budget, head_ratio=0.72):
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) <= budget:
        return text, False
    h = int(budget * head_ratio)
    t = budget - h
    return (tok.decode(ids[:h], skip_special_tokens=True) + "\n\n……（中段省略）……\n\n"
            + tok.decode(ids[-t:], skip_special_tokens=True)), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tok", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    ap.add_argument("--ctx", type=int, default=4096)
    ap.add_argument("--per-split", type=int, default=300)
    a = ap.parse_args()

    from transformers import AutoTokenizer
    from datasets import load_dataset

    tok = AutoTokenizer.from_pretrained(a.tok, trust_remote_code=True)
    black = load_blacklist()
    print(f"[blacklist] 训练集已用 uuid {len(black)} 个", file=sys.stderr)

    ds = load_dataset(NEMOTRON, split="r2e_gym", streaming=True)
    it = iter(ds)

    made = {"val": 0, "test": 0}
    files = {s: open(EVAL / s / "traj.jsonl", "w", encoding="utf-8") for s in ("val", "test")}
    seen = set()

    for rec in it:
        if made["val"] >= a.per_split and made["test"] >= a.per_split:
            break
        uid = rec.get("uuid")
        if not uid or uid in black or uid in seen:
            continue
        msgs = rec.get("messages") or []
        body = [m for m in msgs if m.get("role") != "system"]
        u = next((m for m in body if m.get("role") == "user"), None)
        if not u:
            continue
        sys_t = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        traj = render_traj(body[body.index(u) + 1:])
        if not traj.strip():
            continue
        used = len(tok.encode(sys_t + u["content"], add_special_tokens=False))
        if used >= a.ctx - 512:
            continue
        traj2, cut = clip(traj, tok, a.ctx - used)
        # 先填 val，满了填 test
        split = "val" if made["val"] < a.per_split else "test"
        row = {
            "messages": [
                {"role": "system", "content": sys_t},
                {"role": "user", "content": u["content"]},
                {"role": "assistant", "content": traj2},
            ],
            "meta": {"split": split, "domain": "swe_traj_en", "src": NEMOTRON,
                     "repo": rec.get("repo"), "uuid": uid,
                     "ctx_len": used + len(tok.encode(traj2, add_special_tokens=False)),
                     "truncated": cut},
        }
        files[split].write(json.dumps(row, ensure_ascii=False) + "\n")
        made[split] += 1
        seen.add(uid)

    for f in files.values():
        f.close()
    print(json.dumps({"val": made["val"], "test": made["test"], "blacklist": len(black)},
                     ensure_ascii=False, indent=2))
    sys.stdout.flush()
    os._exit(0)      # 强制退出，避开 HF streaming 连接未释放导致的挂起


if __name__ == "__main__":
    main()
