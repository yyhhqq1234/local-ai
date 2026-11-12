#!/usr/bin/env python
"""
rebuild_eval_traj2.py — val/test 轨迹改用 DeepSWE 剩余 task（确定性，不依赖 streaming 顺序）

为什么换源
  Nemotron streaming 的顺序不稳定 + 429 限流，offset 切分导致 test 与训练集重叠 285/379。
  DeepSWE 的 task 是**文件列表**（runs/*/tasks/*/trajectory.json.gz），排序稳定，
  训练只用了 0-150，val/test 取 200-400 → 天然零重叠。

分配
  val  : task 索引 200-299（100 条）
  test : task 索引 300-399（100 条）
"""
from __future__ import annotations
import argparse, gzip, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "train" / "data"
EVAL = DATA / "eval"
REPO = "kaitchup/DeepSWE1.1-trajectories-Qwen3.8-27B"
RAW = DATA / "agent-traj" / "deepswe" / "_raw"


def render(steps):
    system = user = ""
    parts = []
    n_tools = 0
    for st in steps:
        src = st.get("source")
        if src == "system":
            system = st.get("message") or system
        elif src == "user":
            user = st.get("message") or user
        elif src == "agent":
            blocks = []
            rc = (st.get("reasoning_content") or "").strip()
            if rc:
                blocks.append(f"【思考】{rc}")
            for tc in (st.get("tool_calls") or []):
                a = tc.get("arguments")
                if isinstance(a, (dict, list)):
                    a = json.dumps(a, ensure_ascii=False)
                blocks.append(f"[CALL {tc.get('name','tool')}] {a or ''}")
                n_tools += 1
            for r in ((st.get("observation") or {}).get("results") or []):
                c = (r.get("content") or "").strip()
                if c:
                    blocks.append(f"【observation】{c}")
            if blocks:
                parts.append("【assistant】" + "\n".join(blocks))
    return system, user, "\n\n".join(parts), {"turns": len(steps), "tool_calls": n_tools}


def fetch(rel: str) -> Path:
    from huggingface_hub import hf_hub_download
    try:
        return Path(hf_hub_download(REPO, rel, repo_type="dataset"))
    except Exception:
        import urllib.request
        RAW.mkdir(parents=True, exist_ok=True)
        dst = RAW / rel.replace("/", "__")
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        url = f"https://hf-mirror.com/datasets/{REPO}/resolve/main/{rel}"
        tmp = dst.with_suffix(dst.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                c = r.read(1 << 20)
                if not c:
                    break
                f.write(c)
        tmp.replace(dst)
        return dst


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
    ap.add_argument("--val-start", type=int, default=200)
    ap.add_argument("--test-start", type=int, default=300)
    ap.add_argument("--n", type=int, default=100)
    a = ap.parse_args()

    from huggingface_hub import HfApi
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tok, trust_remote_code=True)
    api = HfApi(endpoint=os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com")
    files = sorted(f for f in api.list_repo_files(REPO, repo_type="dataset")
                   if f.endswith("/trajectory.json.gz"))
    print(f"[info] DeepSWE 共 {len(files)} 个 task", file=sys.stderr)

    plan = [("val", a.val_start, a.n), ("test", a.test_start, a.n)]
    for split, start, n in plan:
        out = EVAL / split / "traj.jsonl"
        made = 0
        with open(out, "w", encoding="utf-8") as fo:
            for rel in files[start:start + n]:
                try:
                    d = json.load(gzip.open(fetch(rel), "rt", encoding="utf-8"))
                    system, user, traj, meta = render(d.get("steps") or [])
                    if not user or not traj.strip():
                        continue
                    used = len(tok.encode(system + user, add_special_tokens=False))
                    if used >= a.ctx - 512:
                        continue
                    traj2, cut = clip(traj, tok, a.ctx - used)
                    agent = d.get("agent") or {}
                    fm = d.get("final_metrics") or {}
                    fo.write(json.dumps({
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                            {"role": "assistant", "content": traj2},
                        ],
                        "meta": {"split": split, "domain": "swe_traj_deepswe", "src": REPO,
                                 "task": d.get("task_name"), "model": agent.get("model_name"),
                                 "scaffold": agent.get("name"), "file": rel,
                                 "peak_ctx": fm.get("peak_context_tokens"),
                                 **meta,
                                 "ctx_len": used + len(tok.encode(traj2, add_special_tokens=False)),
                                 "truncated": cut},
                    }, ensure_ascii=False) + "\n")
                    made += 1
                except Exception as e:
                    if made < 3:
                        print(f"  [skip] {type(e).__name__}: {str(e)[:80]}", file=sys.stderr)
                    continue
                time.sleep(0.2)
        print(f"[{split}] {made} 条 → {out}", file=sys.stderr)
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
