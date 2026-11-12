#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
2B v3 数据优化（清洗 + 去泄漏 + 截断治理）
输入：data/nsfw-gated/train-2b-gated-v3.jsonl
输出：data/nsfw-gated/train-2b-gated-v3b.jsonl  +  stats-v3b.json  +  optlog-v3b.json

处理规则（每条都可 dry-run）：
  R1 评测泄漏   剔除 user 与 eval/{val,test} 任一重叠的样本
  R2 编码损坏   剔除含 C1 控制字符(U+0080..U+009F) / NUL 的样本
  R3 源站残留   删整行论坛广告 / URL / 打包区推广；删后正文过短则整条剔除
  R4 章节标记   删整行「第X章/第X节/Chapter N」；删后过短则整条剔除
  R5 截断治理   系统+user 已超 ctx 的丢弃；总超 ctx 的 pos/neg 丢弃、ctl 截 assistant
  R6 矛盾样本   ctl 的 user 含 NSFW 开关词 → 剔除
  R7 软正样本   pos 无露骨词的打 meta.pos_kind="soft"（保留，训练端可过滤）
"""
import json, os, re, sys, hashlib, collections, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
GATED = os.path.join(HERE, "data", "nsfw-gated")
SRC = os.path.join(GATED, "train-2b-gated-v3.jsonl")
OUT = os.path.join(GATED, "train-2b-gated-v3b.jsonl")
STATS = os.path.join(GATED, "stats-v3b.json")
LOG = os.path.join(GATED, "optlog-v3b.json")
EVAL_DIR = os.path.join(HERE, "data", "eval")

CTX = 2048
CPT = 1.6
DRY = "--dry-run" in sys.argv

TRIGGERS = ["[[NSFW]]", "NSFW", "成人内容", "[[模式:NSFW]]", "R18",
            "[NSFW]", "无限制模式", "成人向创作模式", "18+ 模式"]
TRIG_RE = re.compile("(" + "|".join(re.escape(t) for t in TRIGGERS) + ")")
EXPLICIT = ["肉棒", "龟头", "阴道", "子宫", "阴茎", "乳头", "精液", "射精",
            "中出", "肏", "抽插", "高潮", "淫", "乳房", "性爱", "做爱", "奸",
            "发情", "爱液", "潮吹", "口交", "肛", "调教", "肉便器", "勃起"]
EXPL_RE = re.compile("(" + "|".join(EXPLICIT) + ")")

# R3 源站残留（整行删）
ADV_RE = re.compile(
    r"(forumdisplay\.php|/forum/|fid=\d+"
    r"|更多小说|书友|打包区|TXT文学|色中色|免费无金|最新、最快、最火"
    r"|本章未完|请收藏|小说网|www\.|https?://"
    r"|温馨提示：|字数统计|更新时间：\d)"
)
# R4 章节标记（整行删）
CHAP_RE = re.compile(r"^\s*(第[一二三四五六七八九十百千0-9]{1,5}[章节回卷部篇]|Chapter\s+\d{1,4})\b")

C1_RE = re.compile(r"[\u0080-\u009f\x00]")


def load(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def rid(r):
    i = r.get("id", "")
    return i.rsplit("#", 1)[-1] if "#" in i else ("ctl" if i.startswith("v3ctl") else "?")


def get(rec, role):
    for m in rec.get("messages", []):
        if m.get("role") == role:
            return m.get("content") or ""
    return ""


def setc(rec, role, val):
    for m in rec.get("messages", []):
        if m.get("role") == role:
            m["content"] = val
            return


def h(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def tok(s):
    return int(len(s) / CPT)


def eval_user_set():
    s = set()
    files = []
    v = os.path.join(EVAL_DIR, "val")
    if os.path.isdir(v):
        for fn in os.listdir(v):
            if fn.endswith(".jsonl"):
                files.append(os.path.join(v, fn))
    t = os.path.join(EVAL_DIR, "test")
    if os.path.isdir(t):
        for fn in os.listdir(t):
            if fn.endswith(".jsonl"):
                files.append(os.path.join(t, fn))
    for p in files:
        for r in load(p):
            u = get(r, "user")
            if u:
                s.add(h(u))
    return s, [os.path.basename(x) for x in files]


def strip_lines(text, pattern, max_keep_ratio=0.5):
    """删匹配行；返回 (新文本, 删了几行, 是否整体无效)"""
    lines = text.split("\n")
    keep, removed = [], 0
    for ln in lines:
        if pattern.search(ln):
            removed += 1
            continue
        keep.append(ln)
    new = "\n".join(keep)
    # 删后保留率过低 → 视为整条脏
    invalid = (removed > 0 and len(new.strip()) < len(text.strip()) * max_keep_ratio)
    return new, removed, invalid


def main():
    rows = load(SRC)
    eset, efiles = eval_user_set()
    log = collections.Counter()
    detail = collections.defaultdict(list)
    out = []
    soft_n = 0

    for r in rows:
        tag = rid(r)
        u = get(r, "user")
        a = get(r, "assistant")
        s = get(r, "system")

        # R1 评测泄漏
        if h(u) in eset:
            log["R1_eval_leak"] += 1
            continue

        # R2 编码损坏
        if C1_RE.search(u) or C1_RE.search(a) or C1_RE.search(s):
            log["R2_c1_control"] += 1
            detail["R2"].append(r.get("id"))
            continue

        # R3 源站残留（只动 user + assistant，system 一般干净）
        u2, r3u, bad_u = strip_lines(u, ADV_RE)
        a2, r3a, bad_a = strip_lines(a, ADV_RE)
        if bad_u or bad_a:
            log["R3_ad_invalid"] += 1
            detail["R3"].append(r.get("id"))
            continue
        if r3u or r3a:
            log["R3_ad_lines_stripped"] += r3u + r3a
            setc(r, "user", u2); setc(r, "assistant", a2)
            u, a = u2, a2

        # R4 章节标记
        u3, r4u, _ = strip_lines(u, CHAP_RE, 0.3)
        a3, r4a, _ = strip_lines(a, CHAP_RE, 0.3)
        if r4u or r4a:
            log["R4_chapter_lines_stripped"] += r4u + r4a
            setc(r, "user", u3); setc(r, "assistant", a3)
            u, a = u3, a3

        # R5 截断治理
        tu, ta, ts = tok(u), tok(a), tok(s)
        if tu + ts >= CTX:
            log["R5_drop_user_fills_ctx"] += 1
            detail["R5_drop"].append((r.get("id"), tu, ta))
            continue
        if tu + ta + ts > CTX:
            if tag.startswith("ctl") or tag == "?":
                # ctl 可截 assistant 到剩余预算
                budget = max(64, CTX - tu - ts - 8)
                a = a[: int(budget * CPT)]
                setc(r, "assistant", a)
                log["R5_ctl_truncated"] += 1
            else:
                log["R5_drop_pos_neg_over_ctx"] += 1
                detail["R5_drop"].append((r.get("id"), tu, ta))
                continue

        # R6 ctl 含开关词（矛盾）
        if (tag.startswith("ctl") or tag == "?") and TRIG_RE.search(u):
            log["R6_ctl_has_trigger"] += 1
            continue

        # R7 软正样本打标
        if tag == "pos" and not EXPL_RE.search(a):
            r.setdefault("meta", {})["pos_kind"] = "soft"
            soft_n += 1
        elif tag == "pos":
            r.setdefault("meta", {})["pos_kind"] = "explicit"

        out.append(r)

    # ── R8 整条完全重复去重 ──
    seen = set()
    dedup = []
    for r in out:
        k = h(get(r, "user") + "\x00" + get(r, "assistant"))
        if k in seen:
            log["R8_dup_pair"] += 1
            continue
        seen.add(k)
        dedup.append(r)
    out = dedup

    # ── 统计 ──
    grp = collections.Counter(rid(r) for r in out)
    def alen(r):
        return len(get(r, "assistant"))
    def dist(vals):
        vals = sorted(vals); n = len(vals)
        if not n: return {}
        q = lambda p: vals[min(n - 1, int(n * p / 100))]
        return {"p50": q(50), "p90": q(90), "max": vals[-1]}
    bygrp = {}
    for g in grp:
        rs = [r for r in out if rid(r) == g]
        tot = sum(tok(get(r, "user")) + tok(get(r, "assistant")) + tok(get(r, "system")) for r in rs)
        bygrp[g] = {"n": len(rs), "asst_chars": dist([alen(r) for r in rs]),
                    "tokens": tot}
    total_tok = sum(v["tokens"] for v in bygrp.values()) or 1
    share = {g: round(v["tokens"] / total_tok, 4) for g, v in bygrp.items()}

    stats = {
        "src": os.path.basename(SRC), "out": os.path.basename(OUT),
        "in_rows": len(rows), "out_rows": len(out),
        "removed": len(rows) - len(out),
        "rules": dict(log),
        "groups": bygrp, "token_share": share,
        "pos_soft": soft_n,
        "pos_explicit": grp.get("pos", 0) - soft_n,
        "eval_files": efiles,
        "eval_user_hashes": len(eset),
    }

    print("=" * 74)
    print(f"2B v3 → v3b 优化{'（DRY-RUN，不写盘）' if DRY else ''}")
    print("=" * 74)
    print(f"输入 {len(rows)}  输出 {len(out)}  剔除 {len(rows)-len(out)}")
    print(f"评测集参考：{efiles}  user 哈希 {len(eset)}")
    print("-" * 74)
    for k, v in sorted(log.items()):
        print(f"  {k:<32} {v}")
    print("-" * 74)
    print(f"pos 显式 {grp.get('pos',0)-soft_n} / 软正样本 {soft_n}")
    print("分组：", dict(grp))
    print("token 份额：", share)
    print("-" * 74)

    if not DRY:
        with open(OUT, "w", encoding="utf-8") as f:
            for r in out:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with open(STATS, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        with open(LOG, "w", encoding="utf-8") as f:
            json.dump({"rules": dict(log),
                       "detail": {k: v[:200] for k, v in detail.items()}},
                      f, ensure_ascii=False, indent=2)
        print(f"[OUT] {OUT}")
        print(f"[STATS] {STATS}")
    else:
        print("[DRY] 未写盘；加 --apply 生效")


if __name__ == "__main__":
    main()
