#!/usr/bin/env python
"""
build_traj_multi.py — 多源 agent 轨迹 → 本项目 SFT 格式

支持的数据源（结构各不相同）
  nemotron     nvidia/Nemotron-SWE-v1            messages[] 多轮（OpenHands）
  potato       PotatoHD/agent-coding-traces-public  text = ChatML 全文（Claude Code 真迹）
  swe-rebench  ibragim-bad/swe_rebench_07_2026_trajectories  events[].messages

统一产出
  {"messages":[system,user,assistant], "meta":{domain,src,license,turns,ctx_len,truncated,...}}

用法
  python train/lines/_shared/scripts/build_traj_multi.py --src potato --limit 200 --target-ctx 8192 \
      --out train/lines/9b-oxcoder/data/agent-traj/claude-code/cc-8k.jsonl
  python train/lines/_shared/scripts/build_traj_multi.py --src swe-rebench --limit 200 --target-ctx 8192 \
      --out train/lines/9b-oxcoder/data/agent-traj/swe-rebench/rebench-8k.jsonl
"""
from __future__ import annotations
import argparse, json, os, re, sys, itertools
from pathlib import Path

SRC_REPO = {
    "nemotron":    ("nvidia/Nemotron-SWE-v1", "r2e_gym"),
    "potato":      ("PotatoHD/agent-coding-traces-public", "train"),
    "swe-rebench": ("ibragim-bad/swe_rebench_07_2026_trajectories", "train"),
}

KITTY_SYS = ("你是 kitty 逆向工作台的执行层，直接调用工具完成逆向与工程任务。"
             "工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，"
             "按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。")


def parse_chatml(text: str) -> list[dict]:
    """解析 <|im_start|>role\\ncontent<|im_end|> 结构"""
    msgs = []
    for chunk in text.split("<|im_start|>")[1:]:
        if "<|im_end|>" in chunk:
            head, rest = chunk.split("<|im_end|>", 1)
        else:
            head, rest = chunk, ""
        if "\n" in head:
            role, content = head.split("\n", 1)
        else:
            role, content = head, ""
        content = (content + rest).strip()
        if content or role.strip():
            msgs.append({"role": role.strip(), "content": content})
    return msgs


def extract(src: str, rec: dict) -> tuple[str, str, dict]:
    """返回 (system, user, 额外 meta)；轨迹部分由调用方从 msgs 取"""
    if src == "nemotron":
        msgs = rec.get("messages") or []
        sys_txt = msgs[0]["content"] if msgs and msgs[0].get("role") == "system" else ""
        body = [m for m in msgs if m.get("role") != "system"]
        u = next((m for m in body if m.get("role") == "user"), None)
        if not u:
            raise ValueError("no user message")
        meta = {"repo": rec.get("repo"), "license": rec.get("license"),
                "turns": len(msgs), "uuid": rec.get("uuid"), "domain": "swe_traj_en"}
        return sys_txt, u["content"], meta, body[body.index(u) + 1:]

    if src == "potato":
        text = rec.get("text") or ""
        msgs = parse_chatml(text)
        if not msgs:
            raise ValueError("empty chatml")
        sys_txt = msgs[0]["content"] if msgs[0]["role"] == "system" else ""
        body = [m for m in msgs if m["role"] != "system"]
        u = next((m for m in body if m["role"] == "user"), None)
        if not u:
            raise ValueError("no user message")
        meta = {"source": rec.get("source"), "license": "see-dataset-card",
                "turns": len(msgs), "domain": "claude_code_traj_en"}
        return sys_txt, u["content"], meta, body[body.index(u) + 1:]

    if src == "swe-rebench":
        # events 按 seq 重排：tool_call{input,tool} / tool_result{content} / assistant_message{content}
        events = sorted(rec.get("events") or [], key=lambda e: e.get("seq", 0))
        prompts = rec.get("prompts") or []
        sys_txt = next((p.get("content") for p in prompts if p.get("role") == "system"), "") or ""
        user_txt = next((p.get("content") for p in prompts if p.get("role") == "user"), "") or ""
        if not user_txt:
            raise ValueError("no user prompt")
        steps = []
        for e in events:
            t = e.get("type")
            if t == "tool_call":
                inp = e.get("input")
                if isinstance(inp, (dict, list)):
                    inp = json.dumps(inp, ensure_ascii=False)
                steps.append({"role": "assistant", "content": f"[CALL {e.get('tool','tool')}] {inp or ''}"})
            elif t == "tool_result":
                steps.append({"role": "tool", "content": e.get("content") or ""})
            elif t in ("assistant_message", "final_message"):
                steps.append({"role": "assistant", "content": e.get("content") or ""})
        part = rec.get("participant") or {}
        usage = rec.get("usage") or {}
        meta = {"repo": rec.get("repository"), "license": "see-dataset-card",
                "turns": len(steps), "instance_id": rec.get("instance_id"),
                "model": part.get("model"), "scaffold": part.get("scaffold"),
                "steps": usage.get("steps"), "tool_calls": usage.get("tool_calls"),
                "domain": "claude_code_traj_en"}
        return sys_txt, user_txt, meta, steps

    raise ValueError(f"unknown src {src}")


def render(steps: list[dict]) -> str:
    out = []
    for m in steps:
        role = m.get("role")
        txt = (m.get("content") or "").strip()
        calls = m.get("tool_calls") or []
        if role == "assistant":
            parts = []
            if txt:
                parts.append(txt)
            for c in calls:
                fn = c.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, (dict, list)):
                    args = json.dumps(args, ensure_ascii=False)
                parts.append(f"[CALL {fn.get('name','tool')}] {args or ''}")
            if parts:
                out.append("【assistant】" + "\n".join(parts))
        elif role in ("tool", "observation", "function"):
            if txt:
                out.append("【observation】" + txt)
        elif role == "user":
            if txt:
                out.append("【user】" + txt)
    return "\n\n".join(out)


def clip(text: str, tok, budget: int, head_ratio=0.72) -> tuple[str, bool]:
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) <= budget:
        return text, False
    head = int(budget * head_ratio)
    tail = budget - head
    return (tok.decode(ids[:head], skip_special_tokens=True)
            + "\n\n……（中段省略）……\n\n"
            + tok.decode(ids[-tail:], skip_special_tokens=True)), True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, choices=list(SRC_REPO))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--target-ctx", type=int, default=8192)
    ap.add_argument("--min-ctx", type=int, default=2048)
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    ap.add_argument("--system-mode", choices=["original", "kitty"], default="original")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from datasets import load_dataset
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer, trust_remote_code=True)
    repo, split = SRC_REPO[a.src]
    ds = load_dataset(repo, split=split, streaming=True)
    it = itertools.islice(ds, a.offset, a.offset + a.limit if a.limit else None)

    Path(os.path.dirname(a.out) or ".").mkdir(parents=True, exist_ok=True)
    st = {"src": a.src, "repo": repo, "total": 0, "kept": 0, "err": 0, "truncated": 0}
    ctxs = []
    with open(a.out, "w", encoding="utf-8") as f:
        for rec in it:
            st["total"] += 1
            try:
                sys_txt, user_txt, meta, steps = extract(a.src, rec)
                traj = render(steps)
                if not traj.strip():
                    st["err"] += 1
                    continue
                system = KITTY_SYS if a.system_mode == "kitty" else sys_txt
                used = len(tok.encode(system + user_txt, add_special_tokens=False))
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
                f.write(json.dumps({
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_txt},
                        {"role": "assistant", "content": traj2},
                    ],
                    "meta": {**meta, "src": repo, "ctx_len": ctx_len, "truncated": cut},
                }, ensure_ascii=False) + "\n")
                st["kept"] += 1
                ctxs.append(ctx_len)
            except Exception as e:
                st["err"] += 1
                if st["err"] <= 3:
                    print(f"  [skip] {type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
    if ctxs:
        ctxs.sort()
        q = lambda p: ctxs[min(int(len(ctxs) * p), len(ctxs) - 1)]
        st.update(ctx_p50=q(.5), ctx_p90=q(.9), ctx_max=ctxs[-1])
    st["out"] = a.out
    print(json.dumps(st, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
