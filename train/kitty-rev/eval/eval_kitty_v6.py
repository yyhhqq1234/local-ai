#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_kitty_v6.py — 带 agent loop 的 kitty 能力判分器

与 eval_kitty_v5.py 的唯一差别：**取数方式**。
v5 只发一轮，模型发一个 tool_call 就结束 → 多步能力结构性测不出（real-trajectory 恒 0）。
v6 跑真 agent loop：收到 tool_calls 就用 mock 回包喂回去，最多 N 轮，
把「全部轮次的 content + 全部轮次的 tool_calls」一起交给同一套判据。

判据本身一行不改（从 v5 import），保证 v5/v6 分数可直接对比：
  同权重 + 同题集 + 同判据，只差「给模型几轮」。
"""
import argparse
import json
import os
import re
import sys
import time

_EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.dirname(_EVAL_DIR)          # kitty-rev 根（与 v5 的 HERE 定义一致）
sys.path.insert(0, _EVAL_DIR)
import eval_kitty_v5 as V5   # noqa: E402

# ★ v5 的致命缺陷：V5.TOOLS 只塞了 4 个 kitty 工具，模型看不到 kitty_jadx / kitty_rea_trace，
#   于是它只能回「这个工具不在我的工具集里」→ tool-route 结构性必败。
#   v6 改用全量 64 工具的 function schema（与训练集 v6-mix 的 tools 数组同源）。
_TOOLS_JSON = os.path.join(HERE, "data", "intent3", "v6-mix", "tools.json")
if os.path.exists(_TOOLS_JSON):
    _all = json.load(open(_TOOLS_JSON, encoding="utf-8"))["function_schemas"]
    V5.TOOLS = _all
    print(f"[tools] 注入全量 schema {len(_all)} 个工具（v5 只给了 {4} 个）", flush=True)
else:
    print(f"[tools] 警告：{_TOOLS_JSON} 不存在，沿用 v5 的 {len(V5.TOOLS)} 个工具", flush=True)

# ── mock 回包：按工具名给真实格式的回包（A 通道格式见 kitty_ops 冻结表）──────
MOCK = {
    "kitty_ops": "OK|66 ops|PING VER LP OPEN CUR R W ALLOC MODENUM DIS S_NEW S_GET S_NEXT S_FREE "
                 "P_BACK P_BACK_RES P_WALK JOB_STAT RANGE_INFO MEMDUMP_HEX DBG_ATTACH DBG_BP "
                 "DBG_GO DBG_REGS KM_API KM_INFO KM_R KM_W KM_PA KM_PR LUA SYNC_STAT SYNC_ARCHIVE",
    "kitty_status": "OK|bridge=v0.2.9|cmd_age_ms=12|rep_age_ms=8|pending=0|host=KittyCE pid=21044",
    "kitty_ce": "OK|1234",
    "kitty_pchain": "OK|hits=3|7ff6dadb3a20<-7ff6dadc1f00+0x18<-7ff6dc0a2010+0x2c8",
    "kitty_dbg": "OK|attached",
    "kitty_sym": "OK|exports=6|InitPlugin|RunTask|FreeTask|GetVersion|DllMain|resolve va=0x180001a20",
    "kitty_inject": "OK|injected|module=hook.dll|base=0x7ff6dc110000",
    "kitty_prot": "OK|protect=RWX|size=4096",
    "kitty_wpb": "OK|wrote=3|verify=ok|pte_restored=1",
    "kitty_dump": "OK|dumped=1703936|unmapped|match=99.87%",
    "kitty_acescan": "OK|gate=green|R/KM_R/KM_PR 一致|writeback 全通|evidence=logs/acescan.jsonl",
    "kitty_variants": "OK|6 ce + 2 dbg|ws-svip-full|ws-svip-simple|ws-dbg-dbg64",
    "kitty_drvio": "OK|services=2|files=2|devices=2|software=7",
    "kitty_init": "OK|L0=ok|L1=ok|L2=ok",
    "kitty_dualview": "OK|gate=green|三视图一致",
    "kitty_km": "OK|pid=13297|peProcess=0xffffa10b3c2d5080|open=1|mem=1|regions=1|phys=1|"
                "va=0x7ff6dadb0000|pa=0x1f3a2000",
    "kitty_patch": "OK|machine=0x8664|sections=5|.text vsize=0x1a000 raw=0x1a000|hits=3|patched",
    "kitty_asm": "OK|bytes=31 C0 C3|len=3",
    "kitty_selftest": "OK|A 12/12|C 9/9|E 5/5|rc=0",
    "kitty_die": "OK|packer=(none)|compiler=MSVC(19.3x)",
    "kitty_ghidra": "OK|functions=842|analyze done|out=logs/ghidra",
    "kitty_ida": "OK|functions=214|strings=389|rc=0",
    "kitty_idamcp": "OK|status=list describe call",
    "kitty_net": "OK|started|pid=15420|requests=214",
    "kitty_proto": "OK|format=protobuf|fields=1",
    "kitty_rea": "OK|tools=170",
    "kitty_rea_binary": "OK|arch=aarch64|sections=22|symbols=148",
    "kitty_rea_function": "OK|pseudo=ok|asm=ok|xrefs=7",
    "kitty_rea_javascript": "OK|modules=42|imports=118",
    "kitty_rea_trace": "OK|trail=4|check_serial→win→printf|files=2",
    "kitty_rea_android": "OK|package=com.example.app|minSdk=24|perms=12",
    "kitty_rea_compare": "OK|delta=high|added=1|changed=3",
    "kitty_rea_method": "OK|smali=ok|lines=142",
    "kitty_rea_callpath": "OK|paths=2|DllMain→InitPlugin→RunTask→WriteFile",
    "kitty_rea_recover_js": "OK|recovered=42|out=logs/js",
    "kitty_engines": "OK|engine=unity|route=il2cpp",
    "kitty_cpp2il": "OK|assemblies=41|out=logs/cpp2il",
    "kitty_gdre": "OK|scripts=318|scenes=94",
    "kitty_uedump": "OK|sdk=ok|classes=8421",
    "kitty_il2cppdumper": "OK|classes=8421|methods=138204",
    "kitty_assetrip": "OK|exported=1842|textures=902",
    "kitty_dnspy": "OK|deobf=ok|renamed=2140|types=1204",
    "kitty_bepinex": "OK|installed|BepInEx 5.4.23|x64",
    "kitty_uexplorer": "OK|injected|UnityExplorer loaded",
    "kitty_fmodel": "OK|entries=28104|exported=28104",
    "kitty_ue4ss": "OK|injected|UE4SS v3.0.1",
    "kitty_jadx": "OK|sources=1248|out=logs/jadx-app/sources|hits=7|rc=0",
    "kitty_apktool": "OK|decoded|smali=3 dex|rc=0",
    "kitty_apkscan": "OK|packer=(none)|dex=3|anti_vm=false",
    "kitty_frida": "OK|attached|script loaded|pid=9012",
    "kitty_unpack": "OK|collected|dex=5",
    "kitty_lua": "OK|decompiled|lines=842",
    "kitty_trail": "OK|appended",
    "kitty_settings": "OK|target-set done|mode=task",
    "kitty_loop": "OK|round done|red=0",
    "kitty_loop_status": "OK|host=up|target=none|red=0|patterns=12",
    "kitty_drv": "OK|Private_Access=started|mhtglyts=started|both green",
    "kitty_spawn": "OK",
}
DEFAULT_MOCK = "OK|done"

# 引擎对「未声明/写成 markup 的工具名」会做 recovery（日志：tool markup recovered |
# undeclared tool, kept 1），此时 message.tool_calls 为空，但正文里留着工具名。
# 这类「调了但没解析到」不能算「没调」——从正文兜底抓已知工具名。
_KNOWN = set()
try:
    _tj = json.load(open(_TOOLS_JSON, encoding="utf-8")) if os.path.exists(_TOOLS_JSON) else {}
    _KNOWN = {t["name"] for t in _tj.get("tools", [])}
except Exception:
    pass
_TOOLNAME_RE = re.compile(r"\b(kitty_[a-z0-9_]+|reverse_[a-z0-9_]+)\b")


def calls_from_text(t):
    if not t:
        return []
    out, seen = [], set()
    for m in _TOOLNAME_RE.finditer(t):
        nm = m.group(1)
        if nm in _KNOWN and nm not in seen:
            seen.add(nm)
            out.append({"name": nm, "args": {}, "_from_text": True})
    return out


# 事实抽取（用于「mock 回包里的关键事实有没有被正文复述」）
# 审查指出：用「mock 前 40 字连续原文 in 正文」是错方向 —— 模型复述是摘取/改写，
# 不会 40 字连续命中，结果恒空等于没取证。正解是 token 级三集合交集。
_FACT_RE = re.compile(
    r"[A-Z][A-Z0-9_]{2,}"                       # OP 名 / 常量：KM_INFO, S_NEW, DBG_ATTACH
    r"|\b[\w.+-]+=[\w.+-]+"                     # key=value：pid=21044, gate=green
    r"|\b0x[0-9a-fA-F]+\b"                      # 地址
    r"|\b\d+(?:\.\d+)?\s*(?:B|KB|MB|GB|GiB)\b"  # 带单位数字
)


def facts_of(s):
    """抽事实 token（小写归一，长度≥3，过滤纯结构噪声）"""
    out = set()
    for x in _FACT_RE.findall(s or ""):
        v = x.strip().lower()
        if len(v) >= 3 and v not in ("ok|", "err|"):
            out.add(v)
    return out


def mock_reply(call):
    nm = call.get("name") or ""
    return MOCK.get(nm, DEFAULT_MOCK)


def agent_run(base, model, user, max_tokens, rounds):
    """真 agent loop：tool_calls → mock 回包 → 继续，最多 rounds 轮。"""
    msgs = [{"role": "system", "content": V5.SYS},
            {"role": "user", "content": user}]
    texts, all_calls, traj = [], [], []
    for r in range(rounds):
        try:
            resp = V5.post(base, model, msgs, max_tokens=max_tokens)
        except Exception as e:
            traj.append({"round": r + 1, "error": f"{type(e).__name__}: {e}"})
            break
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        # thinking 模型：content 可能空、全部预算落在 reasoning_content。
        # 旧写法只读 content → 把「想了但没说」判成「什么都没做」（题18/19/21 的真相）。
        c_raw = msg.get("content") or ""
        r_raw = msg.get("reasoning_content") or ""
        txt = (c_raw if c_raw.strip() else r_raw).strip()
        calls = V5.calls_of(resp)
        # 引擎 recovery 丢掉的调用：只补进判据（all_calls），不用于继续 loop
        # （没有真实 tool_call_id 可回填，硬续会让模型困惑）。
        fb = calls_from_text(txt) if not calls else []
        if txt:
            texts.append(txt)
        traj.append({"round": r + 1, "text_chars": len(txt),
                     "calls": [c.get("name") for c in calls],
                     "recovered_from_text": [c["name"] for c in fb]})
        if fb:
            all_calls.extend(fb)
        if not calls:
            break
        all_calls.extend(calls)
        # 回填 assistant 的 tool_calls，再逐条给 tool 回包
        mocks = [mock_reply(c) for c in calls]
        back = []
        for j, c in enumerate(calls):
            back.append({"id": f"c{r}_{j}", "type": "function",
                         "function": {"name": c.get("name"),
                                      "arguments": json.dumps(c.get("args") or {},
                                                              ensure_ascii=False)}})
        msgs.append({"role": "assistant", "content": txt, "tool_calls": back})
        for j, m in enumerate(mocks):
            msgs.append({"role": "tool", "tool_call_id": f"c{r}_{j}", "content": m})
        # 审查项：real-trajectory 存在「靠复述 mock 回包过题」的假 PASS 通道。
        # 存**不截断**的原始文本（截断会把 7ff6dadb3a20<-… 多跳链后半切掉），
        # 汇总时用 token 级三集合交集算 mock_echo_facts。
        traj[-1]["_raw_mocks"] = list(mocks)
        traj[-1]["_raw_text"] = txt or ""
    else:
        traj.append({"round": rounds + 1, "note": "max rounds reached"})

    # text：全部轮次 content + 全部 tool_call 的可读形式（与 v5 text_of 同形）
    parts = list(texts)
    for c in all_calls:
        parts.append(f"[tool_call] {c.get('name')} "
                     f"{json.dumps(c.get('args') or {}, ensure_ascii=False)}")
    return "\n".join(parts).strip(), all_calls, traj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="qwen3.8-27b-ablit-swift15-iq2s")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "eval.jsonl"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=4, help="agent loop 最多轮数")
    ap.add_argument("--max-tokens", type=int, default=1536)
    ap.add_argument("--repeat", type=int, default=1,
                    help="整轮重复次数。引擎有 MTP 投机采样，同题同参两次结果可差 ±2 题；"
                         "要可信基线就 >=3，取每题多数票。")
    ap.add_argument("--out", default="")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    rows = []
    with open(a.data, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    if a.limit:
        rows = rows[:a.limit]

    results, votes, t0 = [], {}, time.time()
    last = {}
    for rp in range(a.repeat):
        if a.repeat > 1:
            print(f"\n===== 第 {rp + 1}/{a.repeat} 轮 =====", flush=True)
        for i, row in enumerate(rows, 1):
            user = row["messages"][0]["content"]
            # 去缓存：引擎 context cache 按 prompt 命中，同 prompt 会重放同一响应
            # 加一个 HTML 注释形式的轮次标记，语义不变但 prompt 字节不同 → 缓存失效
            if rp > 0:
                user = user + f"\n<!-- round{rp + 1} -->"
            cat = (row.get("meta") or {}).get("cat", "?")
            txt, calls, traj = agent_run(a.base, a.model, user, a.max_tokens, a.rounds)
            ok, why = V5.judge(row, txt, calls)
            # 取证：本轮正文里复述的 mock 事实（mock ∩ 正文 ∩ 该题参考事实）
            # 若某题命中事实全落在这里，说明可能是「复述 mock」而非真实推理 → S6 需复判
            ref = set(V5._ref_tokens(row))
            echoed = []
            for t in traj:
                mt = facts_of(" ".join(t.pop("_raw_mocks", []) or []))
                tt = facts_of(t.pop("_raw_text", "") or "")
                hit = sorted(mt & tt & ref)
                t["mock_echo_facts"] = hit
                echoed.extend(hit)
            votes.setdefault(i, []).append(bool(ok))
            last[i] = {"i": i, "cat": cat, "why": why, "calls": len(calls),
                       "chars": len(txt), "traj": traj,
                       "mock_echo_facts": sorted(set(echoed))}
            print(f"[{i}/{len(rows)}] {cat:26s} {'PASS' if ok else 'FAIL'}  {why}  "
                  f"| rounds={len(traj)} calls={len(calls)} chars={len(txt)}")
            if a.verbose and not ok:
                print("    text: " + txt[:300].replace("\n", " "))

    for i in sorted(last):
        v = votes[i]
        maj = sum(v) * 2 > len(v)          # 多数票
        results.append({**last[i], "pass": maj, "votes": f"{sum(v)}/{len(v)}",
                        "vote_detail": v})

    n = len(results)
    p = sum(1 for r in results if r["pass"])
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["cat"], [0, 0])
        by_cat[r["cat"]][1] += 1
        by_cat[r["cat"]][0] += 1 if r["pass"] else 0

    print("\n" + "=" * 64)
    print(f"[v6 agent-loop 口径] 总通过 {p}/{n} = {p / max(1, n) * 100:.1f}%   "
          f"用时 {time.time() - t0:.0f}s   rounds<={a.rounds} max_tokens={a.max_tokens}")
    for c, (ok, tot) in sorted(by_cat.items(), key=lambda x: -x[1][1]):
        print(f"  {c:28s} {ok}/{tot}")
    print("=" * 64)
    print("注：与 v5 分数对比时必须同权重；v5 是单轮口径，v6 是多轮口径，")
    print("    两者不可混用。要判断训练是否提升，需 v5权重/v6权重 都在 v6 口径下跑。")

    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"judge": "v6-agent-loop", "rounds": a.rounds,
                       "repeat": a.repeat, "vote_rule": "strict-majority (sum(v)*2 > len(v))",
                       "rows_file": a.data, "limit": a.limit, "rows_total": len(rows),
                       "model": a.model, "base": a.base, "max_tokens": a.max_tokens,
                       "pass": p, "total": n,
                       "byCat": {c: {"pass": v[0], "total": v[1]} for c, v in by_cat.items()},
                       "detail": results}, f, ensure_ascii=False, indent=2)
        print(f"[ok] 报告 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
