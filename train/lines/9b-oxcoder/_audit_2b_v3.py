#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
2B v3 训练集深度审计（只读，不改数据）
12 维体检：结构 / 重复 / 长度 / 截断风险 / 标签一致 / 泄漏 / 字符卫生 / 冲突
输出：train/logs/audit-2b-v3.json + 控制台分节报告
"""
import json, os, re, sys, hashlib, collections, unicodedata, random

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
T = os.path.join(DATA, "nsfw-gated", "train-2b-gated-v3.jsonl")
VAL = os.path.join(DATA, "eval", "val", "nsfw-gate.jsonl")
TEST = os.path.join(DATA, "eval", "test")
CTX = 2048          # 训练 --ctx
AVG_CHARS_PER_TOK = 1.6   # 中文粗估
RAND = random.Random(42)

TRIGGERS = ["[[NSFW]]", "NSFW", "成人内容", "[[模式:NSFW]]", "R18",
            "[NSFW]", "无限制模式", "成人向创作模式", "18+ 模式"]
TRIG_RE = re.compile("(" + "|".join(re.escape(t) for t in TRIGGERS) + ")")
EXPLICIT = ["肉棒", "龟头", "阴道", "子宫", "阴茎", "乳头", "精液", "射精",
            "中出", "肏", "抽插", "高潮", "淫", "乳房", "性爱", "做爱", "奸",
            "发情", "爱液", "潮吹", "口交", "肛", "调教", "肉便器", "勃起"]
EXPL_RE = re.compile("(" + "|".join(EXPLICIT) + ")")
PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}|\{[0-9]+\}")

def load(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception as e:
                out.append({"_bad": str(e), "_line": i})
    return out

def R(fid):
    i = fid
    if "#" in i:
        return i.rsplit("#", 1)[-1]
    if i.startswith("v3ctl"):
        return i[:6]
    return "?"

def get(rec, role):
    for m in rec.get("messages", []):
        if m.get("role") == role:
            return m.get("content") or ""
    return ""

def h(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]

def est_tok(s):
    return int(len(s) / AVG_CHARS_PER_TOK)

def main():
    global T
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        T = sys.argv[1]
    rows = load(T)
    res = {"file": T, "total": len(rows), "ctx": CTX, "findings": []}
    F = res["findings"]
    def add(sev, code, msg, n, extra=None):
        F.append({"sev": sev, "code": code, "msg": msg, "n": n, "extra": extra or {}})

    # ── 0 解析 ─────────────────────────────────────────────
    bad = [r for r in rows if "_bad" in r]
    add("blocker" if bad else "ok", "JSON_PARSE", "JSON 解析失败行", len(bad))

    good = [r for r in rows if "_bad" not in r]

    # ── 1 结构 ─────────────────────────────────────────────
    struct_bad = collections.Counter()
    for r in good:
        ms = r.get("messages", [])
        roles = [m.get("role") for m in ms]
        if len(ms) < 2:
            struct_bad["<2 条消息"] += 1; continue
        if roles[-1] != "assistant":
            struct_bad["末条不是 assistant"] += 1
        if roles.count("assistant") != 1:
            struct_bad["assistant 数 != 1"] += 1
        if "user" not in roles:
            struct_bad["无 user"] += 1
        if roles.count("system") > 1:
            struct_bad["多条 system"] += 1
        if roles and roles[0] == "assistant":
            struct_bad["首条是 assistant"] += 1
        for m in ms:
            if not isinstance(m.get("content"), str) or not (m.get("content") or "").strip():
                struct_bad["空 content"] += 1
    add("blocker" if struct_bad else "ok", "STRUCT",
        "结构异常", sum(struct_bad.values()), dict(struct_bad))

    # ── 2 重复 ─────────────────────────────────────────────
    ucnt = collections.Counter(h(get(r, "user")) for r in good)
    acnt = collections.Counter(h(get(r, "assistant")) for r in good)
    dup_u = sum(v - 1 for v in ucnt.values() if v > 1)
    dup_a = sum(v - 1 for v in acnt.values() if v > 1)
    add("warn" if dup_u > len(good) * 0.2 else "ok", "DUP_USER",
        "user 文本重复冗余条数", dup_u,
        {"uniq": len(ucnt), "max_repeat": max(ucnt.values()) if ucnt else 0})
    add("warn" if dup_a > len(good) * 0.2 else "ok", "DUP_ASSIST",
        "assistant 文本重复冗余条数", dup_a,
        {"uniq": len(acnt), "max_repeat": max(acnt.values()) if acnt else 0})

    # 完全重复（user+assistant）
    pair = collections.Counter(h(get(r, "user") + "\x00" + get(r, "assistant")) for r in good)
    dup_pair = sum(v - 1 for v in pair.values() if v > 1)
    add("warn" if dup_pair > 0 else "ok", "DUP_PAIR", "整条完全重复", dup_pair)

    # ── 3 长度 / 截断风险（关键） ──────────────────────────
    over = []
    asst_cut = 0
    for r in good:
        u, a = get(r, "user"), get(r, "assistant")
        sysc = get(r, "system")
        tu, ta, ts = est_tok(u), est_tok(a), est_tok(sysc)
        tot = tu + ta + ts
        if tot > CTX:
            over.append((tot, tu, ta, r.get("id")))
            # 若 user 已超 ctx，assistant 会被整段裁掉
            if tu + ts >= CTX:
                asst_cut += 1
    add("blocker" if asst_cut > len(good) * 0.02 else ("warn" if asst_cut else "ok"),
        "TRUNC_DROP_ASSIST",
        "user 已占满 ctx，assistant 整段被裁（样本退化为空标签）", asst_cut,
        {"pct": round(asst_cut / max(1, len(good)) * 100, 2)})
    add("warn" if over else "ok", "TRUNC_OVER",
        "总 token 超 ctx（会被截断）", len(over),
        {"pct": round(len(over) / max(1, len(good)) * 100, 2),
         "sample": sorted(over, reverse=True)[:5]})

    # 长度分布（按组）
    def dist(vals):
        vals = sorted(vals)
        n = len(vals)
        if not n:
            return {}
        q = lambda p: vals[min(n - 1, int(n * p / 100))]
        return {"n": n, "p10": q(10), "p50": q(50), "p90": q(90), "p99": q(99), "max": vals[-1]}

    grp = collections.defaultdict(list)
    for r in good:
        grp[R(r.get("id", ""))].append(r)
    res["len_by_group"] = {}
    for g, rs in sorted(grp.items()):
        res["len_by_group"][g] = {
            "user_tok": dist([est_tok(get(r, "user")) for r in rs]),
            "asst_tok": dist([est_tok(get(r, "assistant")) for r in rs]),
        }

    # ── 4 退化样本 ─────────────────────────────────────────
    degen = collections.Counter()
    for r in good:
        a = get(r, "assistant")
        u = get(r, "user")
        if len(a.strip()) < 10:
            degen["assistant <10 字符"] += 1
        if a.strip() == u.strip():
            degen["assistant == user"] += 1
        if len(set(a.strip())) <= 3 and len(a.strip()) > 5:
            degen["字符种类≤3（乱码/重复）"] += 1
        if re.fullmatch(r"[\s\W_]+", a):
            degen["纯标点空白"] += 1
    add("blocker" if any(k.startswith("assistant <") or "==" in k for k in degen) else "ok",
        "DEGENERATE", "退化样本", sum(degen.values()), dict(degen))

    # ── 分组（后续多段共用） ──────────────────────────────
    pos = [r for r in good if R(r.get("id", "")) == "pos"]
    neg = [r for r in good if R(r.get("id", "")) == "neg3"]
    ctl = [r for r in good if R(r.get("id", "")) not in ("pos", "neg3")]

    # ── 5 占位符残留 / 模板泄漏（只查我方合成桶，ctl 是代码会误报） ──
    synth = [r for r in good if R(r.get("id", "")) in ("neg3", "v3ctlw")]
    ph = sum(1 for r in synth if PLACEHOLDER_RE.search(get(r, "assistant")))
    add("blocker" if ph else "ok", "PLACEHOLDER",
        "合成样本残留未替换占位符", ph, {"scope_n": len(synth)})
    tpl_leak = sum(1 for r in synth
                   if re.search(r"(SAMPLE_TPL|OPENERS|TAIL\[|\.format\()", get(r, "assistant")))
    add("blocker" if tpl_leak else "ok", "CODE_LEAK",
        "合成样本泄漏代码/模板标记", tpl_leak)

    # ── 5b 源站残留 / 章节标记（真实脏数据维度） ──────────
    ADV = re.compile(r"(forumdisplay\.php|/forum/|fid=\d+|更多小说|书友|打包区"
                     r"|TXT文学|色中色|免费无金|最新、最快、最火|本章未完"
                     r"|请收藏|小说网|www\.|https?://|温馨提示：)")
    CHAP = re.compile(r"^\s*(第[一二三四五六七八九十百千0-9]{1,5}[章节回卷部篇]"
                      r"|Chapter\s+\d{1,4})\b")
    adv_hit = [(R(r.get("id", "")), r.get("id")) for r in good
               if ADV.search(get(r, "user")) or ADV.search(get(r, "assistant"))]
    add("blocker" if adv_hit else "ok", "AD_RESIDUE",
        "源站广告/URL 残留", len(adv_hit),
        {"by_group": dict(collections.Counter(g for g, _ in adv_hit)),
         "sample": [i for _, i in adv_hit[:3]]})
    chap_hit = sum(1 for r in good
                   if any(CHAP.search(ln) for ln in get(r, "assistant").split("\n")))
    add("warn" if chap_hit else "ok", "CHAPTER_MARK",
        "assistant 残留章节标记行", chap_hit)

    # ── 5c pos/neg 真配对率（去开关词后 user 是否同一素材） ──
    def strip_trig(s):
        return TRIG_RE.sub("", s).strip()
    pos_u2 = set(h(strip_trig(get(r, "user"))) for r in pos)
    neg_u2 = set(h(strip_trig(get(r, "user"))) for r in neg)
    paired = len(pos_u2 & neg_u2)
    add("warn" if paired < min(len(pos_u2), len(neg_u2)) * 0.3 else "ok",
        "PAIR_RATE", "pos/neg 去开关词后同素材配对数", paired,
        {"pos_uniq": len(pos_u2), "neg_uniq": len(neg_u2),
         "pct_of_neg": round(paired / max(1, len(neg_u2)) * 100, 2)})

    # ── 6 标签一致性 ───────────────────────────────────────
    pos_noexp_all = [r for r in pos if not EXPL_RE.search(get(r, "assistant"))]
    tagged = sum(1 for r in pos_noexp_all
                 if (r.get("meta") or {}).get("pos_kind") == "soft")
    untagged = len(pos_noexp_all) - tagged
    add("blocker" if untagged > len(pos) * 0.05 else ("warn" if untagged else "ok"),
        "POS_NO_EXPLICIT", "pos 无露骨词且未标 soft（真标签错）", untagged,
        {"pct": round(untagged / max(1, len(pos)) * 100, 2),
         "tagged_soft": tagged})

    neg_has_exp = sum(1 for r in neg if EXPL_RE.search(get(r, "assistant")))
    add("blocker" if neg_has_exp else "ok", "NEG_HAS_EXPLICIT",
        "neg 样本 assistant 含露骨词", neg_has_exp)

    pos_notrig = sum(1 for r in pos if not TRIG_RE.search(get(r, "user")))
    add("warn" if pos_notrig > len(pos) * 0.02 else "ok", "POS_NO_TRIGGER",
        "pos 样本 user 无开关词（该开却没标记）", pos_notrig,
        {"pct": round(pos_notrig / max(1, len(pos)) * 100, 2)})

    ctl_trig = sum(1 for r in ctl if TRIG_RE.search(get(r, "user")))
    add("warn" if ctl_trig else "ok", "CTL_HAS_TRIGGER",
        "ctl 样本 user 含开关词但回复是常规（矛盾样本）", ctl_trig)

    neg_iscopy = sum(1 for r in neg if get(r, "assistant") == get(r, "user"))
    add("blocker" if neg_iscopy else "ok", "NEG_COPY", "neg 回复==user", neg_iscopy)

    # ── 7 neg 模板骨架聚集度（唯一率之外的近似重复） ───────
    def shingles(s, k=20):
        s = re.sub(r"\s+", "", s)
        return set(s[i:i + k] for i in range(max(0, len(s) - k + 1)))
    samp = RAND.sample(neg, min(400, len(neg)))
    sh = [shingles(get(r, "assistant")) for r in samp]
    jac = []
    for i in range(len(sh)):
        for j in range(i + 1, min(len(sh), i + 25)):
            a, b = sh[i], sh[j]
            if a and b:
                jac.append(len(a & b) / len(a | b))
    avg_j = sum(jac) / len(jac) if jac else 0
    add("warn" if avg_j > 0.35 else "ok", "NEG_NEAR_DUP",
        "neg 两两 20-gram Jaccard 均值（越高越模板化）", round(avg_j, 3),
        {"pairs": len(jac)})

    # ── 8 开关词覆盖 ───────────────────────────────────────
    tc = collections.Counter()
    for r in pos:
        m = TRIG_RE.search(get(r, "user"))
        tc[m.group(0) if m else "(none)"] += 1
    res["trigger_dist_pos"] = dict(tc)
    missing = [t for t in TRIGGERS if tc.get(t, 0) == 0]
    add("warn" if missing else "ok", "TRIGGER_COVER",
        "pos 未覆盖的开关词", len(missing), {"missing": missing})

    # ── 9 与评测集泄漏 ─────────────────────────────────────
    evals = []
    if os.path.exists(VAL):
        evals.append(("val", VAL))
    if os.path.isdir(TEST):
        for fn in os.listdir(TEST):
            if fn.endswith(".jsonl"):
                evals.append((f"test/{fn}", os.path.join(TEST, fn)))
    train_uset = set(h(get(r, "user")) for r in good)
    leak = {}
    for tag, p in evals:
        er = load(p)
        eh = set(h(get(r, "user")) for r in er if "_bad" not in r)
        ov = len(eh & train_uset)
        leak[tag] = {"eval_n": len(eh), "overlap": ov,
                     "pct": round(ov / max(1, len(eh)) * 100, 2)}
        add("blocker" if ov else "ok", "EVAL_LEAK",
            f"训练集与 {tag} 的 user 重叠", ov, leak[tag])
    res["eval_leak"] = leak

    # ── 10 字符卫生 ────────────────────────────────────────
    ctrl = nul = bom = lone = 0
    for r in good:
        for m in r.get("messages", []):
            c = m.get("content") or ""
            if any(unicodedata.category(ch) == "Cc" and ch not in "\n\t\r" for ch in c):
                ctrl += 1
            if "\x00" in c:
                nul += 1
            if c.startswith("\ufeff"):
                bom += 1
    add("blocker" if (nul or bom) else ("warn" if ctrl else "ok"),
        "CHAR_HYGIENE", "控制字符/空字节/BOM", ctrl + nul + bom,
        {"ctrl": ctrl, "nul": nul, "bom": bom})

    # ── 11 pos 素材强度分布（防过强/过弱） ─────────────────
    pos_exp_cnt = [len(EXPL_RE.findall(get(r, "assistant"))) for r in pos]
    res["pos_explicit_hits"] = dist(pos_exp_cnt)
    weak = sum(1 for c in pos_exp_cnt if c <= 1)
    add("warn" if weak > len(pos) * 0.15 else "ok", "POS_WEAK",
        "pos 露骨词命中 ≤1（强度过弱的正样本）", weak,
        {"pct": round(weak / max(1, len(pos)) * 100, 2)})

    # ── 12 组间 user 重叠（pos vs ctl 同素材不同标签） ────
    pos_u = set(h(get(r, "user")) for r in pos)
    ctl_u = set(h(get(r, "user")) for r in ctl)
    neg_u = set(h(get(r, "user")) for r in neg)
    cross = {"pos∩ctl": len(pos_u & ctl_u), "pos∩neg": len(pos_u & neg_u),
             "neg∩ctl": len(neg_u & ctl_u)}
    add("warn" if cross["pos∩ctl"] else "ok", "CROSS_LABEL",
        "同 user 不同标签（矛盾）", sum(cross.values()), cross)
    res["cross_label"] = cross

    # ── 汇总 ───────────────────────────────────────────────
    sev_rank = {"blocker": 3, "warn": 2, "ok": 1}
    worst = max((sev_rank[f["sev"]] for f in F), default=1)
    res["verdict"] = {3: "BLOCKER", 2: "WARN", 1: "PASS"}[worst]
    res["counts"] = {"blocker": sum(1 for f in F if f["sev"] == "blocker"),
                     "warn": sum(1 for f in F if f["sev"] == "warn"),
                     "ok": sum(1 for f in F if f["sev"] == "ok")}

    out = os.path.join(os.path.dirname(HERE), "..", "logs", "audit-2b-v3.json")
    out = os.path.abspath(os.path.join(HERE, "..", "..", "logs", "audit-2b-v3.json"))
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    # ── 控制台 ─────────────────────────────────────────────
    print("=" * 78)
    print(f"2B v3 深度审计 —— {os.path.basename(T)}  {len(good)} 条  ctx={CTX}")
    print("=" * 78)
    icon = {"blocker": "[X]", "warn": "[!]", "ok": "[v]"}
    for f in sorted(F, key=lambda x: -sev_rank[x["sev"]]):
        print(f"{icon[f['sev']]} {f['code']:<20} {f['msg']:<42} n={f['n']}")
        if f["extra"]:
            print(f"      {json.dumps(f['extra'], ensure_ascii=False)[:200]}")
    print("-" * 78)
    print(f"总判定：{res['verdict']}   blocker={res['counts']['blocker']} "
          f"warn={res['counts']['warn']} ok={res['counts']['ok']}")
    print(f"报告：{out}")

if __name__ == "__main__":
    main()
