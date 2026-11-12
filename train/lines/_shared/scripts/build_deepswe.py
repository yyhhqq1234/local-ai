#!/usr/bin/env python
"""
build_deepswe.py — DeepSWE1.1 轨迹（Muse-Glimmer-30B / mini-swe-agent）→ SFT

数据源：kaitchup/DeepSWE1.1-trajectories-Qwen3.8-27B（HF dataset repo，Apache/MIT 见卡片）
结构：runs/<run>/tasks/<task>/trajectory.json.gz
      {schema_version, task_name, agent{name,version,model_name}, steps[], final_metrics}
step：{step, source: system|user|agent, message | reasoning_content+tool_calls+observation}

用法
  python train/lines/_shared/scripts/build_deepswe.py --limit 150 --target-ctx 8192 \
      --out train/lines/9b-oxcoder/data/agent-traj/deepswe/deepswe-8k.jsonl
"""
from __future__ import annotations
import argparse, gzip, json, os, sys, time
from pathlib import Path

REPO = "kaitchup/DeepSWE1.1-trajectories-Qwen3.8-27B"


def render_steps(steps: list[dict]) -> tuple[str, str, dict]:
    """返回 (system, user, meta)；agent 步渲染成 assistant 文本"""
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
                args = tc.get("arguments")
                if isinstance(args, (dict, list)):
                    args = json.dumps(args, ensure_ascii=False)
                blocks.append(f"[CALL {tc.get('name','tool')}] {args or ''}")
                n_tools += 1
            obs = st.get("observation") or {}
            for r in (obs.get("results") or []):
                c = (r.get("content") or "").strip()
                if c:
                    blocks.append(f"【observation】{c}")
            if blocks:
                parts.append("【assistant】" + "\n".join(blocks))
    return system, user, {"turns": len(steps), "tool_calls": n_tools}, "\n\n".join(parts)


def clip(text: str, tok, budget: int, head_ratio=0.72):
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) <= budget:
        return text, False
    head = int(budget * head_ratio)
    tail = budget - head
    return (tok.decode(ids[:head], skip_special_tokens=True)
            + "\n\n……（中段省略）……\n\n"
            + tok.decode(ids[-tail:], skip_special_tokens=True)), True


def fetch(rel: str, raw_dir: Path) -> Path:
    """下载 trajectory.json.gz：先试 hf_hub_download，失败退 requests 直下（绕开 Windows 缓存/符号链接问题）"""
    from huggingface_hub import hf_hub_download
    try:
        return Path(hf_hub_download(REPO, rel, repo_type="dataset"))
    except Exception:
        import urllib.request
        raw_dir.mkdir(parents=True, exist_ok=True)
        dst = raw_dir / rel.replace("/", "__")
        if dst.exists() and dst.stat().st_size > 0:
            return dst
        endpoint = os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com"
        url = f"{endpoint}/datasets/{REPO}/resolve/main/{rel}"
        tmp = dst.with_suffix(dst.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        tmp.replace(dst)
        return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100, help="最多处理多少个 task")
    ap.add_argument("--target-ctx", type=int, default=8192)
    ap.add_argument("--min-ctx", type=int, default=2048)
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sleep", type=float, default=1.0, help="每文件间隔秒数（防 429）")
    a = ap.parse_args()

    from huggingface_hub import HfApi
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer, trust_remote_code=True)
    api = HfApi(endpoint=os.environ.get("HF_ENDPOINT") or "https://hf-mirror.com")
    files = [f for f in api.list_repo_files(REPO, repo_type="dataset")
             if f.endswith("/trajectory.json.gz")]
    files.sort()
    print(f"仓库共 {len(files)} 个 trajectory，处理前 {a.limit} 个", file=sys.stderr)
    raw_dir = Path(a.out).parent / "_raw"

    Path(os.path.dirname(a.out) or ".").mkdir(parents=True, exist_ok=True)
    st = {"repo": REPO, "candidates": len(files), "tried": 0, "kept": 0, "err": 0, "truncated": 0}
    ctxs = []
    with open(a.out, "w", encoding="utf-8") as fo:
        for rel in files[: a.limit]:
            st["tried"] += 1
            try:
                p = fetch(rel, raw_dir)
                d = json.load(gzip.open(p, "rt", encoding="utf-8"))
                system, user, meta, traj = render_steps(d.get("steps") or [])
                if not user or not traj.strip():
                    st["err"] += 1
                    continue
                used = len(tok.encode(system + user, add_special_tokens=False))
                if used >= a.target_ctx - 512:
                    st["err"] += 1
                    continue
                traj2, cut = clip(traj, tok, a.target_ctx - used)
                ctx_len = used + len(tok.encode(traj2, add_special_tokens=False))
                if ctx_len < a.min_ctx:
                    st["err"] += 1
                    continue
                if cut:
                    st["truncated"] += 1
                agent = d.get("agent") or {}
                fm = d.get("final_metrics") or {}
                fo.write(json.dumps({
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": traj2},
                    ],
                    "meta": {
                        "domain": "swe_traj_deepswe",
                        "src": REPO,
                        "license": "see-dataset-card",
                        "task": d.get("task_name"),
                        "model": agent.get("model_name"),
                        "scaffold": agent.get("name"),
                        "peak_ctx": fm.get("peak_context_tokens"),
                        "total_steps": fm.get("total_steps"),
                        **meta,
                        "ctx_len": ctx_len,
                        "truncated": cut,
                    },
                }, ensure_ascii=False) + "\n")
                st["kept"] += 1
                ctxs.append(ctx_len)
            except Exception as e:
                st["err"] += 1
                if st["err"] <= 3:
                    print(f"  [skip] {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            if a.sleep:
                time.sleep(a.sleep)
    if ctxs:
        ctxs.sort()
        q = lambda p: ctxs[min(int(len(ctxs) * p), len(ctxs) - 1)]
        st.update(ctx_p50=q(.5), ctx_p90=q(.9), ctx_max=ctxs[-1])
    st["out"] = a.out
    print(json.dumps(st, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
