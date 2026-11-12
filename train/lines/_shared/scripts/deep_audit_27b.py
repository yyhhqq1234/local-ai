#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""deep_audit_27b.py — 27B 训练集深度缺陷审查（D1–D15）

比 audit_27b_data.py（R1–R11，规则/格式面）更深一层：查「会训练出坏行为」的结构与语义缺陷。

    D1  角色序列合法性（system→user→assistant；tool 必须紧跟带 tool_calls 的 assistant）
    D2  tools 字段覆盖率（tools=null 时 chat template 不渲染工具 schema → 学不会发 tool_call）
    D3  编造工具名（assistant 提到的 kitty_* / rea 工具不在真实目录里）
    D4  每类规模与长度画像（类别失衡）
    D5  长度 vs 训练 ctx（超长被静默截断 → 学到半截答案）
    D6  答案自重复（8-gram 重复率 → 退化成复读机）
    D7  近重复 user（SimHash 64bit，汉明距离 ≤3）
    D8  模板霸屏（同 cat 内完全同答案 / 同前缀的克隆数）
    D9  占位符 / 环境残留（WORKSPACE / autodl / TODO / {{ }} / 占位）
    D10 空答案 / 复读 user
    D11 控制字符 / 零宽 / U+FFFD / 乱码
    D12 门控成对性与拒绝语多样性（neg 只有一种句式 → 换词就漏）
    D13 结构断裂计数（tool 消息无对应 tool_calls）
    D14 pos 答案以元话术开头（"作为/抱歉/我无法"）
    D15 语言错配（英文占比 >80% 的中文类目行）

用法：
    python deep_audit_27b.py --data <jsonl> --out <dir> [--ctx 8192] [--tok <tokenizer 目录>]
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import sys
import unicodedata

KITTY_TOOL_RE = re.compile(r"\bkitty_[a-z0-9_]+")
REA_TOOL_RE = re.compile(r"\b(?:inspect|analyze|trace|recover|compare)_[a-z0-9_]+\b")

META_OPEN = ("作为", "抱歉", "我无法", "对不起", "我理解", "以下是我", "根据你的要求")
RESIDUE_RE = re.compile(
    r"(<WORKSPACE>|<REMOTE_TMP>|<REMOTE_ENV>|<REMOTE_PUB>|autodl|BaiduNetdisk"
    r"|/root/miniconda3|C:\\\\Users|TODO|FIXME|占位|待补|XXX|\{\{|\}\}|<PLACEHOLDER>)"
)
CTRL_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
REFUSAL_HINT = ("当前为常规模式", "不输出露骨", "常规模式", "无法", "不能", "不提供", "恕不")


def sh(text: str) -> int:
    """64bit SimHash（按 3-gram 词片）"""
    if not text:
        return 0
    v = [0] * 64
    s = re.sub(r"\s+", "", text)
    grams = [s[i:i + 3] for i in range(max(0, len(s) - 2))]
    if not grams:
        grams = [s]
    for g in grams:
        h = int.from_bytes(hashlib.blake2b(g.encode("utf-8"), digest_size=8).digest(), "big")
        for b in range(64):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if v[b] > 0:
            out |= 1 << b
    return out


def ham(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def rep8(text: str) -> float:
    """8-gram 重复率 = 1 - 唯一8gram/总8gram"""
    s = re.sub(r"\s+", "", text)
    if len(s) < 40:
        return 0.0
    grams = [s[i:i + 8] for i in range(len(s) - 7)]
    return 1.0 - len(set(grams)) / len(grams)


def ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    n = sum(1 for c in text if ord(c) < 128)
    return n / len(text)


def get_texts(row):
    msgs = row.get("messages") or []
    sys_t = "".join(m.get("content") or "" for m in msgs if m.get("role") == "system")
    usr_t = "".join(m.get("content") or "" for m in msgs if m.get("role") == "user")
    asst_t = "".join(m.get("content") or "" for m in msgs if m.get("role") == "assistant")
    tc_t = json.dumps(
        [m.get("tool_calls") for m in msgs if m.get("tool_calls")], ensure_ascii=False
    )
    return sys_t, usr_t, asst_t, tc_t, msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ctx", type=int, default=8192, help="训练 max_length")
    ap.add_argument("--tok", default="", help="tokenizer 目录；给了就精确测长度")
    ap.add_argument("--near-dup-cap", type=int, default=200000)
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    tok = None
    if a.tok:
        try:
            from transformers import AutoTokenizer
            tok = AutoTokenizer.from_pretrained(a.tok, trust_remote_code=True)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] tokenizer 加载失败，长度改用字符估算: {e}")

    n = 0
    cats = collections.Counter()
    d = collections.defaultdict(list)          # 规则 -> 证据(前若干条)
    cnt = collections.Counter()

    role_pat = collections.Counter()
    tool_call_ids = set()
    orphan_tool = 0
    tools_null = 0
    tools_nonnull = 0
    toolcall_rows_wo_tools = 0
    rows_wo_system = 0
    system_not_first = 0

    ans_hash = collections.Counter()
    ans_prefix = collections.defaultdict(collections.Counter)
    ans_hash_meta = {}
    refusals = collections.Counter()

    len_chars = []
    len_tokens = []
    over_ctx = 0

    sh_buckets = collections.defaultdict(list)
    near_pairs = 0
    near_examples = []

    kitty_names = collections.Counter()
    unknown_names = collections.Counter()

    per_cat_len = collections.defaultdict(list)
    per_cat_ref = collections.Counter()
    per_cat_n = collections.Counter()

    with open(a.data, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                row = json.loads(line)
            except Exception as e:  # noqa: BLE001
                cnt["D0_json_bad"] += 1
                d["D0_json_bad"].append({"line": ln, "err": str(e)[:120]})
                continue

            cat = ((row.get("meta") or {}).get("cat") or "<none>")
            cats[cat] += 1
            per_cat_n[cat] += 1
            sys_t, usr_t, asst_t, tc_t, msgs = get_texts(row)

            # ---------- D1 角色序列 ----------
            if not msgs:
                cnt["D1_empty_messages"] += 1
                d["D1_empty_messages"].append({"line": ln, "cat": cat})
            else:
                seq = tuple(m.get("role") for m in msgs)
                role_pat[seq] += 1
                if msgs[0].get("role") != "system":
                    rows_wo_system += 1
                    if rows_wo_system <= 8:
                        d["D1_no_system"].append({"line": ln, "cat": cat, "first": msgs[0].get("role")})
                elif any(m.get("role") == "system" for m in msgs[1:]):
                    system_not_first += 1
                # tool 必须紧跟带 tool_calls 的 assistant
                for i, m in enumerate(msgs):
                    if m.get("role") == "tool":
                        prev = msgs[i - 1] if i else {}
                        if prev.get("role") != "assistant" or not prev.get("tool_calls"):
                            orphan_tool += 1
                            if len(d["D13_orphan_tool"]) < 8:
                                d["D13_orphan_tool"].append({"line": ln, "cat": cat, "idx": i})
                for m in msgs:
                    for tc in (m.get("tool_calls") or []):
                        tid = tc.get("id")
                        if tid:
                            tool_call_ids.add((ln, tid))

            # ---------- D2 tools 覆盖 ----------
            tools = row.get("tools")
            has_tc = bool(tc_t and tc_t != "[]")
            if tools:
                tools_nonnull += 1
            else:
                tools_null += 1
                if has_tc:
                    toolcall_rows_wo_tools += 1

            # ---------- D3 工具名 ----------
            body = asst_t + tc_t
            for nm in KITTY_TOOL_RE.findall(body):
                kitty_names[nm] += 1

            # ---------- D5 长度 ----------
            if tok is not None:
                try:
                    ntok = len(tok(sys_t + usr_t + asst_t + tc_t, add_special_tokens=False)["input_ids"])
                except Exception:  # noqa: BLE001
                    ntok = int(len(sys_t + usr_t + asst_t + tc_t) / 1.6)
            else:
                ntok = int(len(sys_t + usr_t + asst_t + tc_t) / 1.6)
            nch = len(sys_t) + len(usr_t) + len(asst_t) + len(tc_t)
            len_chars.append(nch)
            len_tokens.append(ntok)
            per_cat_len[cat].append(ntok)
            if ntok > a.ctx:
                over_ctx += 1
                if len(d["D5_over_ctx"]) < 10:
                    d["D5_over_ctx"].append({"line": ln, "cat": cat, "tokens": ntok})

            # ---------- D6 自重复 ----------
            rr = rep8(asst_t)
            if rr > 0.35 and len(asst_t) > 200:
                cnt["D6_self_repeat"] += 1
                if len(d["D6_self_repeat"]) < 10:
                    d["D6_self_repeat"].append({"line": ln, "cat": cat, "rep8": round(rr, 3), "len": len(asst_t)})

            # ---------- D7 近重复 user ----------
            if n <= a.near_dup_cap and usr_t.strip():
                h = sh(usr_t)
                hit = False
                for b in range(4):
                    key = (b * 16, (h >> (b * 16)) & 0xFFFF)
                    for (h2, ln2, cat2) in sh_buckets.get(key, ()):
                        if ham(h, h2) <= 3:
                            near_pairs += 1
                            hit = True
                            if len(near_examples) < 10:
                                near_examples.append({"line": ln, "dup_of": ln2, "cat": cat, "cat2": cat2})
                            break
                    if hit:
                        break
                for b in range(4):
                    key = (b * 16, (h >> (b * 16)) & 0xFFFF)
                    sh_buckets[key].append((h, ln, cat))

            # ---------- D8 模板霸屏 ----------
            if asst_t.strip():
                ah = hashlib.blake2b(asst_t.strip().encode("utf-8"), digest_size=8).hexdigest()
                ans_hash[ah] += 1
                ans_hash_meta.setdefault(ah, {"line": ln, "cat": cat, "head": asst_t.strip()[:60]})
                ans_prefix[cat][asst_t.strip()[:40]] += 1

            # ---------- D9 残留 ----------
            blob = sys_t + usr_t + asst_t + tc_t
            for mt in set(RESIDUE_RE.findall(blob)):
                if mt in ("<WORKSPACE>", "<REMOTE_TMP>", "<REMOTE_ENV>", "<REMOTE_PUB>"):
                    continue  # 已是占位符形态（有意保留），不计残留
                if mt in ("{{", "}}"):
                    continue  # 代码里的 dict/f-string 花括号，不是模板残留
                cnt["D9_residue"] += 1
                if len(d["D9_residue"]) < 12:
                    d["D9_residue"].append({"line": ln, "cat": cat, "hit": mt})
                break

            # ---------- D10 空答案 / 复读 ----------
            if not asst_t.strip():
                if has_tc:
                    cnt["D10_empty_but_toolcall"] += 1   # 合法的 agent 第一步：只有 tool_call
                else:
                    cnt["D10_empty_answer"] += 1
                    if len(d["D10_empty_answer"]) < 8:
                        d["D10_empty_answer"].append({"line": ln, "cat": cat})
            elif usr_t.strip() and asst_t.strip() == usr_t.strip():
                cnt["D10_echo_user"] += 1

            # ---------- D11 控制字符 / 乱码 ----------
            if CTRL_RE.search(blob) or "\ufffd" in blob:
                cnt["D11_ctrl_or_mojibake"] += 1
                if len(d["D11_ctrl_or_mojibake"]) < 8:
                    d["D11_ctrl_or_mojibake"].append({"line": ln, "cat": cat})
            elif "Ã" in blob or "â€" in blob:
                cnt["D11_ctrl_or_mojibake"] += 1

            # ---------- D12 门控 ----------
            # cat 里有 nsfw/neg 语义的用答案是否含拒绝提示判定
            neg_like = any(k in cat for k in ("neg", "refus", "safe"))
            pos_like = any(k in cat for k in ("nsfw", "pos", "explicit"))
            is_ref = any(h in asst_t for h in REFUSAL_HINT)
            if is_ref:
                per_cat_ref[cat] += 1
                refusals[asst_t.strip()[:50]] += 1
            if pos_like and is_ref:
                cnt["D12_pos_but_refuse"] += 1
            if neg_like and not is_ref:
                cnt["D12_neg_but_not_refuse"] += 1

            # ---------- D14 元话术开头 ----------
            astr = asst_t.strip()
            if astr.startswith(META_OPEN):
                cnt["D14_meta_open"] += 1
                if len(d["D14_meta_open"]) < 10:
                    d["D14_meta_open"].append({"line": ln, "cat": cat, "head": astr[:40]})

            # ---------- D15 语言错配 ----------
            if astr and astr.isascii() is False and ascii_ratio(astr) > 0.8 and per_cat_n[cat] > 100:
                cnt["D15_ascii_in_cjk"] += 1

    # ---------- 汇总 ----------
    def q(vals, p):
        if not vals:
            return 0
        vals = sorted(vals)
        k = min(len(vals) - 1, int(len(vals) * p))
        return vals[k]

    top_ans = ans_hash.most_common(15)
    dup_rows = sum(c - 1 for c in ans_hash.values() if c > 1)
    prefix_top = {c: v.most_common(5) for c, v in ans_prefix.items()}

    report = {
        "data": a.data,
        "rows": n,
        "ctx": a.ctx,
        "counts": dict(cnt),
        "cats": dict(cats),
        "D1_role_patterns_top": [{"seq": list(k), "n": v} for k, v in role_pat.most_common(10)],
        "D1_rows_without_system": rows_wo_system,
        "D1_system_not_first": system_not_first,
        "D2_tools_null": tools_null,
        "D2_tools_nonnull": tools_nonnull,
        "D2_toolcall_rows_without_tools": toolcall_rows_wo_tools,
        "D3_kitty_names_top": kitty_names.most_common(40),
        "D5_tokens_p50": q(len_tokens, .5), "D5_tokens_p90": q(len_tokens, .9),
        "D5_tokens_p99": q(len_tokens, .99), "D5_tokens_max": max(len_tokens) if len_tokens else 0,
        "D5_over_ctx": over_ctx,
        "D7_near_pairs": near_pairs,
        "D7_examples": near_examples,
        "D8_distinct_answers": len(ans_hash),
        "D8_dup_answer_rows": dup_rows,
        "D8_top_answers": [{"n": c, **ans_hash_meta[h]} for h, c in top_ans],
        "D8_prefix_top": {k: v for k, v in prefix_top.items()},
        "D12_refusal_variants": refusals.most_common(10),
        "D12_refusal_variant_count": len(refusals),
        "per_cat": {
            c: {
                "rows": per_cat_n[c],
                "tokens_p50": q(per_cat_len[c], .5),
                "tokens_p90": q(per_cat_len[c], .9),
                "refusal_rows": per_cat_ref[c],
            } for c in per_cat_n
        },
        "evidence": {k: v for k, v in d.items()},
    }
    with open(os.path.join(a.out, "deep-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # ---------- Markdown ----------
    L = []
    L.append(f"# 27B 深度缺陷审查 — {os.path.basename(a.data)}\n")
    L.append(f"- 行数 **{n}** · ctx **{a.ctx}** · tokenizer **{'精确' if tok else '字符估算(/1.6)'}**\n")
    L.append("## 缺陷计数\n")
    L.append("| 规则 | 计数 | 含义 |")
    L.append("|---|---|---|")
    meaning = {
        "D0_json_bad": "JSON 解析失败",
        "D1_empty_messages": "messages 为空",
        "D5_over_ctx": "超 ctx（训练时静默截断）",
        "D6_self_repeat": "8-gram 重复率>0.35（复读倾向）",
        "D9_residue": "环境/TODO/占位残留",
        "D10_empty_answer": "assistant 空答案",
        "D10_echo_user": "答案复读 user",
        "D11_ctrl_or_mojibake": "零宽/控制符/乱码",
        "D12_pos_but_refuse": "pos 行却拒答",
        "D12_neg_but_not_refuse": "neg 行未拒答",
        "D13_orphan_tool": "tool 消息无对应 tool_calls",
        "D14_meta_open": "答案以元话术开头",
        "D15_ascii_in_cjk": "中文类目里英文占比>80%",
    }
    for k in sorted(cnt):
        L.append(f"| {k} | {cnt[k]} | {meaning.get(k,'')} |")
    L.append("")
    L.append("## D1 角色序列\n")
    L.append(f"- 无 system 行：**{rows_wo_system}** · system 不在首位：**{system_not_first}** · 孤儿 tool：**{orphan_tool}**\n")
    for r in report["D1_role_patterns_top"][:6]:
        L.append(f"  - `{'→'.join(r['seq'])}` × {r['n']}")
    L.append("")
    L.append("## D2 tools 覆盖（关键）\n")
    L.append(f"- tools=null 行：**{tools_null}** / {n}（{tools_null/max(1,n)*100:.1f}%）")
    L.append(f"- tools 非空行：**{tools_nonnull}**")
    L.append(f"- 有 tool_calls 但 tools=null：**{toolcall_rows_wo_tools}** → 模型看到 tool_call 结果却从未见过 schema\n")
    L.append("## D5 长度分布（token）\n")
    L.append(f"- p50 **{report['D5_tokens_p50']}** · p90 **{report['D5_tokens_p90']}** · p99 **{report['D5_tokens_p99']}** · max **{report['D5_tokens_max']}**")
    L.append(f"- 超 ctx {a.ctx}：**{over_ctx}** 行\n")
    L.append("## D8 模板霸屏\n")
    L.append(f"- 唯一答案 {len(ans_hash)} 种；重复答案行合计 **{dup_rows}**（占 {dup_rows/max(1,n)*100:.1f}%）\n")
    L.append("| 次数 | cat | 开头 |")
    L.append("|---|---|---|")
    for t in report["D8_top_answers"][:10]:
        head = t["head"].replace("\n", " ").replace("|", "\\|")[:46]
        L.append(f"| {t['n']} | {t['cat']} | `{head}` |")
    L.append("")
    L.append("## D12 门控\n")
    L.append(f"- 拒绝语变体数：**{len(refusals)}**")
    for v, c in refusals.most_common(5):
        L.append(f"  - {c} × `{v.replace(chr(10),' ')[:44]}`")
    L.append("")
    L.append("## 每类画像\n")
    L.append("| cat | 行数 | token p50 | token p90 | 拒答行 |")
    L.append("|---|---|---|---|---|")
    for c, v in sorted(report["per_cat"].items(), key=lambda x: -x[1]["rows"]):
        L.append(f"| {c} | {v['rows']} | {v['tokens_p50']} | {v['tokens_p90']} | {v['refusal_rows']} |")
    L.append("")
    L.append("## D3 工具名出现频次（取前 25）\n")
    for nm, c in kitty_names.most_common(25):
        L.append(f"- `{nm}` × {c}")
    with open(os.path.join(a.out, "deep-report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    print(f"[out] {os.path.join(a.out, 'deep-report.md')}")
    print("\n".join(L[:60]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
