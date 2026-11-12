#!/usr/bin/env python
"""
build_agent_traj.py — 把顶尖模型的 agent 轨迹转成本项目 SFT 格式

来源：nvidia/Nemotron-SWE-v1（51,029 条 OpenHands 轨迹，CC BY 4.0，可商用）
      Qwen3-Coder-480B 合成，issue 源自 SWE-Gym + R2E-Gym-Subset
用途：给 OxCoder-9B 注入"长程工具编排"形状（读→判→改→验 闭环）

用法：
  python train/lines/_shared/scripts/build_agent_traj.py --limit 200 --target-ctx 8192 --out train/lines/9b-oxcoder/data/agent-traj/swe-8k.jsonl
  python train/lines/_shared/scripts/build_agent_traj.py --limit 500 --target-ctx 16384 --out train/lines/9b-oxcoder/data/agent-traj/swe-16k.jsonl

产出格式（与本项目 kitty core 一致）：
  {"messages":[{"role":"system",...},{"role":"user",...},{"role":"assistant",...}],
   "meta":{"domain":"swe_traj_en","repo":...,"license":...,"turns":N,"ctx_len":N,"truncated":bool}}
"""
import argparse, json, os, sys, itertools
from pathlib import Path

def load_stream(limit, offset=0):
    from datasets import load_dataset
    ds = load_dataset("nvidia/Nemotron-SWE-v1", split="r2e_gym", streaming=True)
    it = itertools.islice(ds, offset, offset + limit if limit else None)
    for rec in it:
        yield rec

def render_traj(msgs):
    """把 assistant/tool 交替序列渲染成可读执行过程"""
    out = []
    for m in msgs:
        role = m.get("role")
        if role == "assistant":
            txt = (m.get("content") or "").strip()
            calls = m.get("tool_calls") or []
            parts = []
            if txt:
                parts.append(txt)
            for c in calls:
                fn = (c.get("function") or {})
                name = fn.get("name") or "tool"
                args = fn.get("arguments")
                if isinstance(args, (dict, list)):
                    args = json.dumps(args, ensure_ascii=False)
                parts.append(f"[CALL {name}] {args or ''}")
            if parts:
                out.append("【assistant】" + "\n".join(parts))
        elif role == "tool":
            txt = (m.get("content") or "").strip()
            if txt:
                out.append("【observation】" + txt)
        elif role == "user":
            txt = (m.get("content") or "").strip()
            if txt:
                out.append("【user】" + txt)
    return "\n\n".join(out)

def clip_to_tokens(text, tok, budget, head_ratio=0.72):
    """按 token 预算裁剪，保留头部+尾部（中段用省略标记）"""
    ids = tok.encode(text, add_special_tokens=False)
    if len(ids) <= budget:
        return text, False
    head = int(budget * head_ratio)
    tail = budget - head
    head_txt = tok.decode(ids[:head], skip_special_tokens=True)
    tail_txt = tok.decode(ids[-tail:], skip_special_tokens=True)
    return head_txt + "\n\n……（中段省略）……\n\n" + tail_txt, True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0=全量")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--target-ctx", type=int, default=8192, help="目标 token 长度")
    ap.add_argument("--min-ctx", type=int, default=2048, help="低于此长度丢弃")
    ap.add_argument("--tokenizer", default="train/lines/9b-oxcoder/models/OxCoder-9B")
    ap.add_argument("--out", required=True)
    ap.add_argument("--system-mode", choices=["original", "kitty"], default="original",
                    help="original=保留 OpenHands system（保真）；kitty=换成中文执行层模板")
    a = ap.parse_args()

    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(a.tokenizer, trust_remote_code=True)

    KITTY_SYS = ("你是 kitty 逆向工作台的执行层，直接调用工具完成逆向与工程任务。"
                 "工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，"
                 "按任务直接选工具并给全参数。多步任务要看完上一步回包再决定下一步。")

    Path(os.path.dirname(a.out) or ".").mkdir(parents=True, exist_ok=True)
    stats = {"total": 0, "kept": 0, "too_short": 0, "no_traj": 0, "truncated": 0}
    ctx_lens = []

    with open(a.out, "w", encoding="utf-8") as f:
        for rec in load_stream(a.limit, a.offset):
            stats["total"] += 1
            msgs = rec.get("messages") or []
            if len(msgs) < 5:
                stats["no_traj"] += 1
                continue

            sys_txt = msgs[0].get("content") if msgs and msgs[0].get("role") == "system" else ""
            body = [m for m in msgs if m.get("role") != "system"]
            if not body:
                stats["no_traj"] += 1
                continue

            # user = 首条 user（任务+仓库上下文）
            u_idx = next((i for i, m in enumerate(body) if m.get("role") == "user"), None)
            if u_idx is None:
                stats["no_traj"] += 1
                continue
            user_txt = (body[u_idx].get("content") or "").strip()
            traj_txt = render_traj(body[u_idx + 1:])
            if not traj_txt.strip():
                stats["no_traj"] += 1
                continue

            system = KITTY_SYS if a.system_mode == "kitty" else sys_txt
            # 预算：system + user 已占部分，剩余给轨迹
            used = len(tok.encode(system + user_txt, add_special_tokens=False))
            budget = max(a.target_ctx - used, 1024)
            traj_clipped, cut = clip_to_tokens(traj_txt, tok, budget)
            ctx_len = used + len(tok.encode(traj_clipped, add_special_tokens=False))
            if ctx_len < a.min_ctx:
                stats["too_short"] += 1
                continue
            if cut:
                stats["truncated"] += 1

            sample = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_txt},
                    {"role": "assistant", "content": traj_clipped},
                ],
                "meta": {
                    "domain": "swe_traj_en",
                    "src": "nvidia/Nemotron-SWE-v1",
                    "repo": rec.get("repo"),
                    "dataset": rec.get("dataset"),
                    "license": rec.get("license"),
                    "uuid": rec.get("uuid"),
                    "tools": [t.get("function", {}).get("name") for t in (rec.get("tools") or [])],
                    "turns": len(msgs),
                    "ctx_len": ctx_len,
                    "truncated": cut,
                },
            }
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
            stats["kept"] += 1
            ctx_lens.append(ctx_len)

    if ctx_lens:
        ctx_lens.sort()
        q = lambda p: ctx_lens[min(int(len(ctx_lens) * p), len(ctx_lens) - 1)]
        stats["ctx_p50"] = q(.5); stats["ctx_p90"] = q(.9); stats["ctx_max"] = ctx_lens[-1]
    stats["out"] = a.out
    print(json.dumps(stats, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
