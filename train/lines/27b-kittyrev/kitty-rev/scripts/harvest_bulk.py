# -*- coding: utf-8 -*-
"""harvest_bulk.py —— 从本机全部 DSH 会话存档抽真实轨迹（只读，不解压落盘原文）

源：~/.dsh/sessions/<project>/<session>/session.v*.jsonl.zstd（904 个，跨 19 个项目）
产出：data/real_bulk.jsonl（真实工具轨迹，按项目/会话/轮次可追溯）

筛选（只取"干净可学"的）:
  · 有 ≥2 次工具调用、≤ --max-steps 次
  · 含 kitty_* 调用的优先（--require kitty）；不含但步数合理的归 discipline（可选纳入）
  · turn/end.reason.kind == completed 才算正向；其余进 neg 池
  · 工具结果截断到 --max-tool-chars；assistant 的 reasoning 块丢弃（只学行为）

用法:
  python harvest_bulk.py --dry-run                       # 只统计，看能捞多少
  python harvest_bulk.py --require kitty --projects DrCE  # 只取 kitty 相关项目
  python harvest_bulk.py                                 # 全量（kitty 优先 + 纪律类）
"""
import argparse
import glob
import json
import os
import re
import sys

import zstandard as zstd

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, "data")
SESS = os.path.join(os.path.expanduser("~"), ".dsh", "sessions")
KITTY_RE = re.compile(r"\bkitty_[a-z0-9_]+")


def read_zstd(path):
    try:
        with open(path, "rb") as f:
            dctx = zstd.ZstdDecompressor()
            try:
                with dctx.stream_reader(f, read_across_frames=True) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception:
                f.seek(0)
                raw = f.read()
                out = []
                for chunk in re.split(rb"(?=\x28\xb5\x2f\xfd)", raw):
                    if not chunk:
                        continue
                    try:
                        out.append(zstd.ZstdDecompressor().decompress(chunk, max_output_size=1 << 30))
                    except Exception:
                        continue
                return b"".join(out).decode("utf-8", "replace")
    except Exception:
        return ""


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            out.append(b.get("text", ""))
    return "\n".join(x for x in out if x)


def build_turns(events):
    turns, cur_turn = {}, None
    for e in events:
        t = e.get("type")
        if not t:
            continue
        d = e.get("data") or {}
        if t == "turn/start":
            cur_turn = d.get("turn")
        tn = d.get("turn", cur_turn)
        if tn is None:
            continue
        cur = turns.setdefault(tn, {"turn": tn, "user": "", "msgs": [], "calls": 0, "end": None})
        if t == "user/message" and not cur["user"]:
            cur["user"] = text_of(d.get("content"))
        elif t == "assistant/message":
            cur["msgs"].append({"k": "a", "text": text_of((d.get("message") or {}).get("content")), "seq": e.get("seq", 0)})
        elif t == "tool/call":
            cur["msgs"].append({"k": "c", "name": d.get("name"), "args": d.get("arguments"), "seq": e.get("seq", 0)})
            cur["calls"] += 1
        elif t == "tool/result":
            cur["msgs"].append({"k": "r", "text": text_of((d.get("message") or {}).get("content")), "seq": e.get("seq", 0)})
        elif t == "turn/end":
            cur["end"] = (d.get("reason") or {}).get("kind")
    return [turns[k] for k in sorted(turns)]


def to_messages(turn, max_tool_chars):
    msgs = [{"role": "user", "content": turn["user"].strip()}]
    for m in sorted(turn["msgs"], key=lambda x: x["seq"]):
        if m["k"] == "a":
            if m["text"].strip():
                msgs.append({"role": "assistant", "content": m["text"].strip()})
        elif m["k"] == "c":
            try:
                args = json.loads(m["args"]) if isinstance(m["args"], str) else (m["args"] or {})
            except Exception:
                args = {"_raw": m["args"]}
            payload = json.dumps({"name": m["name"], "arguments": args}, ensure_ascii=False)
            block = "<tool_call>\n" + payload + "\n</tool_call>"
            if msgs and msgs[-1]["role"] == "assistant":
                msgs[-1]["content"] += "\n\n" + block
            else:
                msgs.append({"role": "assistant", "content": block})
        elif m["k"] == "r":
            txt = (m["text"] or "").strip()
            if not txt:
                txt = "(empty)"
            if len(txt) > max_tool_chars:
                txt = txt[:max_tool_chars] + "…[truncated]"
            msgs.append({"role": "tool", "content": txt})
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--min-steps", type=int, default=2)
    ap.add_argument("--max-tool-chars", type=int, default=900)
    ap.add_argument("--max-turns-per-session", type=int, default=40)
    ap.add_argument("--require", choices=["kitty", "any"], default="kitty")
    ap.add_argument("--projects", nargs="*", default=None, help="项目目录名子串过滤")
    ap.add_argument("--max-sessions", type=int, default=0)
    ap.add_argument("--prefix", default="real_bulk", help="输出文件名前缀")
    ap.add_argument("--max-err-ratio", type=float, default=0.5,
                    help="工具回包里 ERR| 占比超此值的轮次丢弃（不干净的轨迹不学）")
    ap.add_argument("--exclude-projects", nargs="*", default=None)
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(SESS, "*", "*", "session.v*.jsonl.zstd")))
    if a.projects:
        files = [f for f in files if any(p.lower() in f.lower() for p in a.projects)]
    if a.max_sessions:
        files = files[:a.max_sessions]

    pos, neg = [], []
    stat = {"files": len(files), "read_ok": 0, "turns": 0, "sessions_hit": 0}

    for path in files:
        txt = read_zstd(path)
        if not txt:
            continue
        stat["read_ok"] += 1
        events = []
        for line in txt.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        sess_id = os.path.basename(os.path.dirname(path))
        project = os.path.basename(os.path.dirname(os.path.dirname(path)))
        turns = build_turns(events)
        hit = 0
        for tr in turns[:a.max_turns_per_session]:
            stat["turns"] += 1
            if not tr["user"] or tr["calls"] < a.min_steps or tr["calls"] > a.max_steps:
                continue
            msgs = to_messages(tr, a.max_tool_chars)
            if not any(m["role"] == "assistant" for m in msgs):
                continue
            if msgs[-1]["role"] != "assistant" or not str(msgs[-1]["content"]).strip():
                continue
            tools_res = [m["content"] for m in msgs if m["role"] == "tool"]
            if tools_res:
                errs = sum(1 for t in tools_res if t.startswith("ERR|"))
                if errs / len(tools_res) > a.max_err_ratio:
                    continue
            blob = json.dumps(msgs, ensure_ascii=False)
            kitty = len(KITTY_RE.findall(blob))
            if a.require == "kitty" and kitty == 0:
                continue
            meta = {"cat": "real-trajectory", "tier": "gold", "src": "bulk",
                    "project": project, "session": sess_id[:8], "turn": tr["turn"],
                    "steps": tr["calls"], "kittyCalls": kitty, "outcome": tr["end"]}
            row = {"messages": msgs, "meta": meta}
            if tr["end"] == "completed":
                pos.append(row)
                hit += 1
            else:
                neg.append(row)
        if hit:
            stat["sessions_hit"] += 1

    stat.update({"pos": len(pos), "neg": len(neg)})
    if pos:
        steps = [p["meta"]["steps"] for p in pos]
        stat["pos_steps"] = {"min": min(steps), "max": max(steps), "avg": round(sum(steps) / len(steps), 1)}
        stat["pos_kitty_avg"] = round(sum(p["meta"]["kittyCalls"] for p in pos) / len(pos), 1)
        proj = {}
        for p in pos:
            proj[p["meta"]["project"]] = proj.get(p["meta"]["project"], 0) + 1
        stat["pos_by_project"] = dict(sorted(proj.items(), key=lambda x: -x[1])[:12])
    print(json.dumps(stat, ensure_ascii=False, indent=2))

    if a.dry_run:
        print("[dry-run] 未落盘")
        return

    os.makedirs(DATA, exist_ok=True)
    for name, rows in ((f"{a.prefix}.jsonl", pos), (f"{a.prefix}_neg.jsonl", neg)):
        with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"[ok] → {DATA}\\{a.prefix}.jsonl ({len(pos)}) / {a.prefix}_neg.jsonl ({len(neg)})")


if __name__ == "__main__":
    sys.exit(main())
