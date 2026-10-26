#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""assert_params_effective.py — 评测产物「参数是否真生效」闸门 (param-gate)

B 组评测落盘后必须先过本闸门，才允许谈结论。

动机 —— 三族真实故障，全靠人眼才发现：
  F16  eval_meta.thinking=false，实际 60/60 条答案以 <think> 开头  -> think 未关
  F17  eval_meta.max_tokens=512，实际 995 字(≈550-580 token)        -> 未透传
  F24  --from-jsonl 100 条被生成但循环仍跑内联名单                  -> 参数被接受没走到执行路径
共同伪装：日志打印「我用了这个参数」，所以人不会怀疑。
唯一可靠验证是断言实际行为，而不是读 meta 字段自证。

检查项（每条输出 PASS / FAIL / N-A + 证据字段）：
  ① n == eval_meta.limit
  ② max(chars)/1.7 <= max_tokens*1.1；判 FAIL 时再用 /3.5 复核防英文误报
  ③ eval_meta.thinking == false ⇒ 不得有 rows[].text/head 以 '<think>' 开头
     （以实际文本为准，不信 meta 字段）
  ④ 名单来源含 jsonl ⇒ list_sha16 不得是 n/a 或空
  ⑤ len(rows) == n == limit（三者相等才算自洽）

模式：
  默认             单文件检查（事实记录：C 组本身 F16/F17 未生效，必然 FAIL）
  --pair C.json B.json   逐字段比 limit / max_tokens / data_sha16 / n / list_sha16
                   （batch 类字段例外：等价性已证明的提速参数）
                   输出 PAIR=CONSISTENT|DIVERGENT；只有 DIVERGENT 才 exit 1
  --gate B.json --baseline C.json
                   组合闸门 = 先 --pair，再对 B 只检自洽类 ①⑤④，②③ 降级 INFO
  --selftest       内置 3 个构造样本（全对 / think 未关 / limit 不符），
                   断言给出正确判定；3/3 才 exit 0

两层语义（lead 2026-10-22 裁决，不许自行放宽）：
  第一层「参数是否真生效」= 单文件 ①-⑤。C 组 re60/bench40/kitty23 必然 FAIL
      （F16 think 未关 / F17 max_tokens 未透传），这是事实记录，**不是**阻断条件。
  第二层「B 组能不能判读」= --pair 字段一致（limit/max_tokens/data_sha16/n/list_sha16）
      且 B 侧 ①⑤④ 自洽。一致时即便两侧 ②③ 都 FAIL 也放行，只打一行 [known-deviation]。
      —— 不改尺子（改了 C 组 24/60 立即失效），也不挡主线。

退出码：0 = 放行 / 1 = 阻断（单文件=有 FAIL；pair=DIVERGENT；gate=不一致或自洽类 FAIL）
        / 2 = 用法或文件错误

用法（python 必须全路径，PATH 里是 0 字节商店别名）：
  C:\\ProgramData\\anaconda3\\python.exe assert_params_effective.py logs\\base-only\\re60.json
  C:\\ProgramData\\anaconda3\\python.exe assert_params_effective.py --pair logs\\c1\\re60.json logs\\b1\\re60.json
  C:\\ProgramData\\anaconda3\\python.exe assert_params_effective.py --selftest
"""

import json
import os
import sys

# ---------------------------------------------------------------- 常量 / 字段别名

ROW_KEYS = ("rows", "results", "samples", "records", "items")
TEXT_KEYS = ("text", "head", "answer", "output", "content", "resp", "response")

# ① ⑤ 用：产出条数候选（优先声明值，最后回落 len(rows)）
N_KEYS = ("n", "n_rows", "n_total", "count")

# ④ 用：只有「名单来源」才要求 list_sha16；评测集路径不算
LIST_SRC_KEYS = ("source", "list_source", "from_jsonl", "names_file", "list_path", "list")

# --pair 例外：等价性已证明的提速参数，不参与一致性判定
PAIR_EXEMPT = {
    "batch", "batch_size", "batchsize", "micro_batch", "micro_batch_size",
    "prefill_chunk", "prefillchunk", "concurrency", "stream", "chunk",
    "kv_dtype", "draft_tokens", "host_kv", "device_kv",
}

PASS, FAIL, NA = "PASS", "FAIL", "N-A"

CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F),
    (0xF900, 0xFAFF), (0xFF00, 0xFFEF),
)


# ---------------------------------------------------------------- 小工具

def _stdout_utf8():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def digits_only(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def num(v):
    """把 60 / '60' / 60.0 / '60条' 尽量变成 float，失败 None。"""
    if digits_only(v):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except ValueError:
            d = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
            try:
                return float(d)
            except ValueError:
                return None
    return None


def first(d, keys, default=None):
    """按 keys 顺序在 dict 里找第一个非 None / 非空串的值。"""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d:
            v = d[k]
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            return v
    return default


def rows_of(doc):
    if isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        return []
    for k in ROW_KEYS:
        v = doc.get(k)
        if isinstance(v, list):
            return v
    return []


def meta_of(doc):
    if isinstance(doc, dict):
        m = doc.get("eval_meta")
        if isinstance(m, dict):
            return m
    return {}


def row_text(row):
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return ""
    for k in TEXT_KEYS:
        v = row.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def row_chars(row, text):
    if isinstance(row, dict):
        c = row.get("chars")
        n = num(c)
        if n is not None:
            return int(n)
    return len(text)


def cjk_ratio(texts, cap_chars=400_000):
    """CJK 字符占比，用于判断 /1.7 是否适用（中文 1 字≈0.6 token，英文 1 字≈0.25 token）。"""
    total = cjk = 0
    for t in texts:
        if not t:
            continue
        for ch in t:
            total += 1
            o = ord(ch)
            if any(lo <= o <= hi for lo, hi in CJK_RANGES):
                cjk += 1
            if total >= cap_chars:
                break
        if total >= cap_chars:
            break
    return (cjk / total) if total else 0.0


def is_think_open(text):
    s = (text or "").lstrip("\ufeff \t\r\n")
    # 全角/变体也算：<think> / ＜think＞ / <|think|> / <thinking>
    s2 = s.replace("＜", "<").replace("＞", ">")
    low = s2[:12].lower()
    return low.startswith("<think") or low.startswith("<|think")


def load_doc(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    raise ValueError("无法解析 JSON: %s" % path)


def clean_sha(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("n/a", "na", "none", "null", "unknown", "-"):
        return None
    return s


# ---------------------------------------------------------------- 检查项

def check01_limit(doc):
    meta, rows = meta_of(doc), rows_of(doc)
    summary = doc.get("summary") if isinstance(doc, dict) else None
    data = doc.get("data") if isinstance(doc, dict) else None

    limit = num(first(meta, ("limit",))) if meta else None
    if limit is None and isinstance(doc, dict):
        limit = num(first(doc, ("limit",)))
    if limit is None and isinstance(doc, dict) and isinstance(doc.get("protocol"), dict):
        limit = num(first(doc["protocol"], ("limit",)))

    n = None
    n_src = None
    for src_name, src in (("eval_meta", meta), ("summary", summary), ("data", data), ("top", doc)):
        if not isinstance(src, dict):
            continue
        for k in N_KEYS:
            if k in src:
                v = num(src[k])
                if v is not None:
                    n, n_src = v, "%s.%s" % (src_name, k)
                    break
        if n is not None:
            break
    if n is None:
        n, n_src = float(len(rows)), "len(rows)"

    ev = {"n": int(n) if n is not None else None, "n_src": n_src,
          "limit": int(limit) if limit is not None else None, "rows": len(rows)}
    if limit is None:
        return {"id": "①", "name": "limit 自洽", "status": NA,
                "evidence": dict(ev, why="产物未声明 limit，无法验证（全量跑标记）")}
    if n == limit:
        return {"id": "①", "name": "limit 自洽", "status": PASS, "evidence": ev}
    return {"id": "①", "name": "limit 自洽", "status": FAIL,
            "evidence": dict(ev, why="n=%d != limit=%d" % (n, limit))}


def check02_chars(doc):
    meta, rows = meta_of(doc), rows_of(doc)
    max_tokens = num(first(meta, ("max_tokens",))) if meta else None
    if max_tokens is None and isinstance(doc, dict):
        proto = doc.get("protocol")
        if isinstance(proto, dict):
            max_tokens = num(first(proto, ("max_tokens",)))
        if max_tokens is None:
            max_tokens = num(first(doc, ("max_tokens",)))

    texts = [row_text(r) for r in rows]
    chars = [row_chars(r, t) for r, t in zip(rows, texts)]
    mx = max(chars) if chars else 0
    nmx = sum(1 for c in chars if c == mx) if chars else 0
    mx_idx = chars.index(mx) if chars else -1
    ratio = cjk_ratio(texts)

    ev = {"max_chars": mx, "rows_at_max": nmx, "max_idx": mx_idx,
          "max_tokens": int(max_tokens) if max_tokens is not None else None,
          "cjk_ratio": round(ratio, 3)}
    if max_tokens is None:
        return {"id": "②", "name": "长度 <= max_tokens", "status": NA,
                "evidence": dict(ev, why="产物未声明 max_tokens")}
    if mx == 0:
        return {"id": "②", "name": "长度 <= max_tokens", "status": FAIL,
                "evidence": dict(ev, why="所有 rows 文本为空（采集/落盘断裂）")}

    cap = max_tokens * 1.1
    tok_zh = mx / 1.7      # 中文保守估计：1 字 ≈ 0.588 token
    tok_en = mx / 3.5      # 英文保守估计：1 字 ≈ 0.286 token（防英文误报复核）
    ev.update({"tok_est_zh": round(tok_zh, 1), "tok_est_en": round(tok_en, 1),
               "cap": round(cap, 1)})

    if tok_zh <= cap:
        return {"id": "②", "name": "长度 <= max_tokens", "status": PASS, "evidence": ev}

    # 复核：/3.5 也过不了 = 硬超；过了但文本是中文 = 仍判超（中文不可能 1 字 0.286 token）
    if tok_en > cap:
        return {"id": "②", "name": "长度 <= max_tokens", "status": FAIL,
                "evidence": dict(ev, why="字数/3.5=%.0f > cap=%.0f，任何语种都超" % (tok_en, cap))}
    if ratio < 0.15:
        return {"id": "②", "name": "长度 <= max_tokens", "status": PASS,
                "evidence": dict(ev, why="英文复核通过(字数/3.5=%.0f<=cap=%.0f, cjk=%.2f)，判英文长文本" % (tok_en, cap, ratio))}
    return {"id": "②", "name": "长度 <= max_tokens", "status": FAIL,
            "evidence": dict(ev, why="中文正文 cjk=%.2f，字数/1.7=%.0f > cap=%.0f，max_tokens 未透传" % (ratio, tok_zh, cap))}


def check03_thinking(doc):
    meta, rows = meta_of(doc), rows_of(doc)
    th = meta.get("thinking") if isinstance(meta, dict) else None
    if th is None and isinstance(doc, dict):
        th = doc.get("thinking")
    if th is None and isinstance(doc, dict) and isinstance(doc.get("protocol"), dict):
        th = doc["protocol"].get("thinking")

    ev = {"meta_thinking": th, "rows": len(rows)}
    if th is not False:
        return {"id": "③", "name": "thinking 真关", "status": NA,
                "evidence": dict(ev, why="thinking 非 false（%r），本项不适用" % (th,))}

    bad = []
    for j, r in enumerate(rows):
        t = row_text(r)
        if is_think_open(t):
            bad.append({"row": j,
                        "idx": (r.get("idx") if isinstance(r, dict) else None),
                        "head12": t.lstrip()[:12]})
    ev.update({"think_rows": len(bad), "first3": bad[:3]})
    if bad:
        return {"id": "③", "name": "thinking 真关", "status": FAIL,
                "evidence": dict(ev, why="%d/%d 条以 <think> 开头，meta 说 false 但实际没关" % (len(bad), len(rows)))}
    return {"id": "③", "name": "thinking 真关", "status": PASS, "evidence": ev}


def check04_listsha(doc):
    meta, rows = meta_of(doc), rows_of(doc)
    top = doc if isinstance(doc, dict) else {}

    # 名单来源：只认 eval_meta / top 上的 source 类字段
    srcs = {}
    for k in LIST_SRC_KEYS:
        v = meta.get(k) if isinstance(meta, dict) else None
        if isinstance(v, str) and v.strip():
            srcs["eval_meta." + k] = v.strip()
        v2 = top.get(k) if isinstance(top, dict) else None
        if isinstance(v2, str) and v2.strip():
            srcs["top." + k] = v2.strip()

    list_sha = clean_sha(first(meta, ("list_sha16",)) if meta else None)
    if list_sha is None:
        list_sha = clean_sha(top.get("list_sha16")) if isinstance(top, dict) else None

    # 评测集路径（data.path）不是名单，不算 ④ 触发条件
    ds_path = ""
    data = top.get("data") if isinstance(top, dict) else None
    if isinstance(data, dict) and isinstance(data.get("path"), str):
        ds_path = data["path"]

    def is_dataset(p):
        if not ds_path:
            return False
        a, b = os.path.basename(p).lower(), os.path.basename(ds_path).lower()
        return a == b or ds_path.lower().endswith(p.lower())

    hits = {k: v for k, v in srcs.items() if "jsonl" in v.lower() and not is_dataset(v)}

    ev = {"list_sha16": list_sha, "sources": srcs, "dataset_path": ds_path,
          "rows": len(rows), "jsonl_list_sources": sorted(hits)}
    if not hits:
        return {"id": "④", "name": "名单参数走到执行路径", "status": NA,
                "evidence": dict(ev, why="无名单类 jsonl 来源（内联名单/评测集路径不算），本项不适用")}
    if list_sha is None:
        return {"id": "④", "name": "名单参数走到执行路径", "status": FAIL,
                "evidence": dict(ev, why="source=%s 但 list_sha16 为 n/a 或空 -> 名单可能被接受未生效" % sorted(hits))}
    return {"id": "④", "name": "名单参数走到执行路径", "status": PASS,
            "evidence": dict(ev, why="名单来源已落 sha，参数进入执行路径")}


def check05_triple(doc):
    meta, rows = meta_of(doc), rows_of(doc)
    summary = doc.get("summary") if isinstance(doc, dict) else None
    data = doc.get("data") if isinstance(doc, dict) else None

    limit = num(first(meta, ("limit",))) if meta else None
    if limit is None and isinstance(doc, dict):
        limit = num(first(doc, ("limit",)))

    n = None
    n_src = None
    for src_name, src in (("eval_meta", meta), ("summary", summary), ("data", data), ("top", doc)):
        if not isinstance(src, dict):
            continue
        for k in N_KEYS:
            if k in src:
                v = num(src[k])
                if v is not None:
                    n, n_src = v, "%s.%s" % (src_name, k)
                    break
        if n is not None:
            break
    if n is None:
        n, n_src = float(len(rows)), "len(rows)"

    ev = {"rows": len(rows), "n": int(n), "n_src": n_src,
          "limit": int(limit) if limit is not None else None}
    if limit is None:
        ok = float(len(rows)) == n
        return {"id": "⑤", "name": "rows==n==limit", "status": PASS if ok else FAIL,
                "evidence": dict(ev, why=None if ok else "rows=%d != n=%d（limit 未声明）" % (len(rows), n))}
    if len(rows) == int(n) == int(limit):
        return {"id": "⑤", "name": "rows==n==limit", "status": PASS, "evidence": ev}
    return {"id": "⑤", "name": "rows==n==limit", "status": FAIL,
            "evidence": dict(ev, why="rows=%d / n=%d / limit=%d 三者不相等" % (len(rows), int(n), int(limit)))}


ALL_CHECKS = (check01_limit, check02_chars, check03_thinking, check04_listsha, check05_triple)


def run_checks(doc):
    return [fn(doc) for fn in ALL_CHECKS]


def verdict(checks):
    fails = [c for c in checks if c["status"] == FAIL]
    return (FAIL if fails else PASS), fails


def render(path, checks):
    overall, fails = verdict(checks)
    print("== param-gate: %s ==" % path)
    for c in checks:
        print("%s %-18s %-4s %s" % (c["id"], c["name"], c["status"],
                                    json.dumps(c["evidence"], ensure_ascii=False, sort_keys=False)))
    n_pass = sum(1 for c in checks if c["status"] == PASS)
    n_na = sum(1 for c in checks if c["status"] == NA)
    print("VERDICT: %s  (%d PASS / %d FAIL / %d N-A)%s"
          % (overall, n_pass, len(fails), n_na,
             "" if not fails else "  失败项: " + ",".join(c["id"] for c in fails)))
    return overall


# ---------------------------------------------------------------- --pair

PAIR_FIELDS = ("limit", "max_tokens", "data_sha16", "n", "list_sha16")


def pair_value(doc, field):
    meta, top = meta_of(doc), (doc if isinstance(doc, dict) else {})
    data = top.get("data") if isinstance(top, dict) else None
    proto = top.get("protocol") if isinstance(top, dict) else None
    if field == "limit":
        for src in (meta, top, proto):
            v = num(first(src, ("limit",))) if isinstance(src, dict) else None
            if v is not None:
                return v
        return None
    if field == "max_tokens":
        for src in (meta, proto, top):
            v = num(first(src, ("max_tokens",))) if isinstance(src, dict) else None
            if v is not None:
                return v
        return None
    if field == "data_sha16":
        v = first(meta, ("data_sha16",))
        if v is None and isinstance(data, dict):
            v = first(data, ("sha16", "data_sha16"))
        return clean_sha(v)
    if field == "list_sha16":
        v = first(meta, ("list_sha16",))
        if v is None and isinstance(top, dict):
            v = first(top, ("list_sha16",))
        return clean_sha(v)
    if field == "n":
        # 声明值优先；都没声明就用实际 rows 条数（等价口径，且两侧同样处理）
        for src in (meta, top.get("summary") if isinstance(top, dict) else None,
                    data, top):
            if not isinstance(src, dict):
                continue
            for k in N_KEYS:
                v = num(src.get(k)) if k in src else None
                if v is not None:
                    return v
        return float(len(rows_of(top)))
    return None


def _dev_note(checks):
    """把 ②③ 的 FAIL 摘成一句证据，供 [known-deviation] 用。"""
    d = {}
    for c in checks:
        if c["id"] in ("②", "③") and c["status"] == FAIL:
            ev = c["evidence"]
            if c["id"] == "②":
                d["②"] = "max_chars=%s>cap=%s" % (ev.get("max_chars"), ev.get("cap"))
            else:
                d["③"] = "%s/%s 条 <think>" % (ev.get("think_rows"), ev.get("rows"))
    return d


def known_deviation_line(checks_c, checks_b):
    """C/B 双方共有的 F16/F17 偏差 —— 只作 INFO，不进 verdict。"""
    dc, db = _dev_note(checks_c), _dev_note(checks_b)
    if not dc and not db:
        return None
    def fmt(d):
        return "; ".join("%sFAIL(%s)" % (k, v) for k, v in sorted(d.items())) or "无"
    return ("[known-deviation] F16 think / F17 max_tokens 属 C/B 共有，已在两侧同时观测"
            "（C:%s ｜ B:%s）→ 不改尺子，不计入判读阻断" % (fmt(dc), fmt(db)))


def norm_suite(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def suite_of(doc):
    """产物声明的 suite（顶层 suite / eval_meta.suite），归一成字母数字。"""
    if isinstance(doc, dict):
        v = doc.get("suite")
        if isinstance(v, str) and v.strip():
            return norm_suite(v)
        m = doc.get("eval_meta")
        if isinstance(m, dict):
            v = m.get("suite")
            if isinstance(v, str) and v.strip():
                return norm_suite(v)
    return ""


def _suite_guard(a_path, b_path, a, b):
    """--pair 只允许同 suite 配对。跨 suite 直接拒绝（比较无意义，不是 DIVERGENT）。"""
    sa, sb = suite_of(a), suite_of(b)
    if sa and sb and sa != sb:
        print("[REFUSE] 跨 suite 比较无意义：%s(suite=%s) vs %s(suite=%s)"
              % (os.path.basename(a_path), sa, os.path.basename(b_path), sb))
        print("         --pair 只接受同一 suite 的 C/B 两文件（如 re60 vs re60）。")
        return False
    if not sa or not sb:
        print("[warn] suite 未声明（A=%r B=%r），按同名前提继续" % (sa, sb))
    return True


def compute_pair(a_path, b_path):
    a, b = load_doc(a_path), load_doc(b_path)
    rows = []
    for f in PAIR_FIELDS:
        va, vb = pair_value(a, f), pair_value(b, f)
        if f in PAIR_EXEMPT:
            rows.append((f, va, vb, NA, "batch 类：等价性已证明的提速参数，不参与一致性判定"))
            continue
        if va is None and vb is None:
            rows.append((f, va, vb, NA, "两侧均未声明"))
            continue
        same = (va == vb) if not (isinstance(va, str) or isinstance(vb, str)) else \
               (str(va).strip().lower() == str(vb).strip().lower())
        rows.append((f, va, vb, PASS if same else FAIL,
                     "" if same else "%r != %r" % (va, vb)))
    diff = [r[0] for r in rows if r[3] == FAIL]
    return rows, diff, run_checks(a), run_checks(b)


def _print_pair_rows(rows):
    for f, va, vb, st, note in rows:
        print("%-12s %-4s C=%-24s B=%-24s %s" % (f, st, va, vb, note))


def run_pair(a_path, b_path):
    """字段一致性 = B 组能不能判读的唯一阻断条件。
    PAIR=CONSISTENT → exit 0（单文件 ②③ FAIL 只作 known-deviation 记录）
    PAIR=DIVERGENT  → exit 1
    """
    rows, diff, cc, cb = compute_pair(a_path, b_path)
    print("== param-gate --pair ==")
    print("C(A) = %s" % a_path)
    print("B    = %s" % b_path)
    if not _suite_guard(a_path, b_path, load_doc(a_path), load_doc(b_path)):
        print("VERDICT: REFUSED")
        return "REFUSED"
    _print_pair_rows(rows)
    pair = "DIVERGENT" if diff else "CONSISTENT"
    print("PAIR=%s  (不一致字段: %s)" % (pair, ",".join(diff) if diff else "无"))
    line = known_deviation_line(cc, cb)
    if line:
        print(line)
    print("-- 单文件行为检查（INFO，不参与本模式 verdict）--")
    for p, ch in ((a_path, cc), (b_path, cb)):
        bad = [c["id"] for c in ch if c["status"] == FAIL]
        print("  %-52s %s %s" % (os.path.basename(p), (FAIL if bad else PASS) + "(info)",
                                 ("失败:" + ",".join(bad)) if bad else ""))
    print("VERDICT: %s" % pair)
    return pair


GATE_IDS = ("①", "⑤", "④")   # 自洽类：B 组必须自己成立
INFO_IDS = ("②", "③")        # 与 C 共有偏差，降级 INFO


def run_gate(b_path, c_path):
    """--gate B --baseline C：先 pair，再对 B 只检 ①⑤④。"""
    rows, diff, cc, cb = compute_pair(c_path, b_path)
    print("== param-gate --gate ==")
    print("baseline(C) = %s" % c_path)
    print("target(B)   = %s" % b_path)
    if not _suite_guard(c_path, b_path, load_doc(c_path), load_doc(b_path)):
        print("GATE: REFUSED")
        return "REFUSED"
    _print_pair_rows(rows)
    pair = "DIVERGENT" if diff else "CONSISTENT"
    print("PAIR=%s  (不一致字段: %s)" % (pair, ",".join(diff) if diff else "无"))

    print("-- B 侧检查（①⑤④ 计入 verdict，②③ INFO）--")
    gate_fail = []
    for c in cb:
        st = c["status"]
        if c["id"] in INFO_IDS:
            print("%s %-18s INFO %s" % (c["id"], c["name"], json.dumps(c["evidence"], ensure_ascii=False)))
            continue
        if st == FAIL:
            gate_fail.append(c["id"])
        print("%s %-18s %-4s %s" % (c["id"], c["name"], st, json.dumps(c["evidence"], ensure_ascii=False)))

    line = known_deviation_line(cc, cb)
    if line:
        print(line)
    ok = (pair == "CONSISTENT") and not gate_fail
    print("GATE: %s  (pair=%s · 自洽类失败: %s)"
          % ("PASS" if ok else "BLOCK", pair, ",".join(gate_fail) if gate_fail else "无"))
    return "PASS" if ok else "BLOCK"


# ---------------------------------------------------------------- --selftest

def _mk(limit, max_tokens, thinking, texts, chars=None, extra_meta=None, with_head=True):
    rows = []
    for i, t in enumerate(texts):
        row = {"i": i + 1, "idx": i, "chars": (chars[i] if chars else len(t))}
        if with_head:
            row["head"] = t
        rows.append(row)
    meta = {"suite": "selftest", "thinking": thinking, "max_tokens": max_tokens,
            "limit": limit, "data_sha16": "0123456789abcdef", "list_sha16": "fedcba9876543210"}
    if extra_meta:
        meta.update(extra_meta)
    return {"eval_meta": meta,
            "summary": {"n": len(rows), "mean_chars": 0},
            "data": {"path": "selftest.jsonl", "sha16": "0123456789abcdef", "rows": len(rows)},
            "rows": rows}


def run_selftest():
    zh = ["这个问题需要先确认工具链是否就绪，然后再决定走哪条执行路径。" * 2,
          "第二步是把参数透传到实际执行路径，而不是只在日志里打印它。" * 2,
          "第三步用实际输出断言，避免参数被接受却没生效。" * 2]

    # 样本 A：全对。3 行，每行约 300 字，max_tokens 512 足够，无 think
    A = _mk(limit=3, max_tokens=512, thinking=False, texts=zh)

    # 样本 B：think 未关。meta 说 false，实际 head 以 <think> 开头
    B = _mk(limit=3, max_tokens=512, thinking=False,
            texts=["<think>\n用户问的是参数是否生效。" + zh[0][:200], zh[1], zh[2]])

    # 样本 C：limit 不符。声明 limit=3，实际 5 条（n 也是 5）
    C = _mk(limit=3, max_tokens=512, thinking=False,
            texts=[zh[0][:120], zh[1][:120], zh[2][:120], zh[0][:120], zh[1][:120]])

    cases = [
        ("A 全对", A, PASS, {"①": PASS, "②": PASS, "③": PASS, "⑤": PASS}),
        ("B think 未关", B, FAIL, {"①": PASS, "③": FAIL}),
        ("C limit 不符", C, FAIL, {"①": FAIL, "⑤": FAIL, "③": PASS}),
    ]

    ok = 0
    print("== param-gate --selftest ==")
    for name, doc, want_overall, want in cases:
        checks = run_checks(doc)
        got_overall, _ = verdict(checks)
        st = {c["id"]: c["status"] for c in checks}
        bad = []
        if got_overall != want_overall:
            bad.append("verdict %s != %s" % (got_overall, want_overall))
        for cid, w in want.items():
            if st.get(cid) != w:
                bad.append("%s %s != %s" % (cid, st.get(cid), w))
        if bad:
            print("  %-14s FAIL  %s" % (name, "; ".join(bad)))
            for c in checks:
                print("      %s %-16s %-4s %s" % (c["id"], c["name"], c["status"],
                                                  json.dumps(c["evidence"], ensure_ascii=False)))
        else:
            ok += 1
            print("  %-14s PASS  verdict=%s  %s" % (name, got_overall,
                                                    " ".join("%s:%s" % (k, v) for k, v in sorted(st.items()))))
    print("SELFTEST: %d/%d %s" % (ok, len(cases), "ALL PASS" if ok == len(cases) else "FAILED"))
    return 0 if ok == len(cases) else 1


# ---------------------------------------------------------------- main

def main(argv):
    _stdout_utf8()
    args = argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if args else 2
    if args[0] == "--selftest":
        return run_selftest()
    if args[0] == "--pair":
        if len(args) < 3:
            print("用法: assert_params_effective.py --pair C.json B.json", file=sys.stderr)
            return 2
        for p in args[1:3]:
            if not os.path.isfile(p):
                print("文件不存在: %s" % p, file=sys.stderr)
                return 2
        rp = run_pair(args[1], args[2])
        if rp == "REFUSED":
            return 2
        return 0 if rp == "CONSISTENT" else 1

    if args[0] == "--gate":
        rest = args[1:]
        if not rest:
            print("用法: assert_params_effective.py --gate B.json --baseline C.json", file=sys.stderr)
            return 2
        b_path = rest[0]
        c_path = ""
        i = 1
        while i < len(rest):
            if rest[i] == "--baseline" and i + 1 < len(rest):
                c_path = rest[i + 1]
                i += 2
            else:
                i += 1
        if not c_path:
            print("--gate 需要 --baseline C.json", file=sys.stderr)
            return 2
        for p in (b_path, c_path):
            if not os.path.isfile(p):
                print("文件不存在: %s" % p, file=sys.stderr)
                return 2
        g = run_gate(b_path, c_path)
        if g == "REFUSED":
            return 2
        return 0 if g == "PASS" else 1

    path = args[0]
    if not os.path.isfile(path):
        print("文件不存在: %s" % path, file=sys.stderr)
        return 2
    try:
        doc = load_doc(path)
    except Exception as e:
        print("解析失败: %s (%s)" % (path, e), file=sys.stderr)
        return 2
    overall = render(path, run_checks(doc))
    return 0 if overall == PASS else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
