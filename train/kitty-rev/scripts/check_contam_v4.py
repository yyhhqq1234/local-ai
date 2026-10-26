#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_contam_v4.py —— contaminated 的 v4 口径离线复算（只读产物 + 只读混料）

背景：`tmp/eval_bare.py:360` 的污染比对集**硬编码**为 `data/large-mix-plus/train.jsonl`（4388 行），
      而 v4 实际混料是 `tmp/mix/train-forge45.jsonl`（4871 行，含 forge 增量 99 补数 + 384 重复）。
      ⇒ 产物里的 `contaminated` 只是**下界**，且对 forge 增量覆盖的题型（op-syntax / decision-chain）
        检出能力尤其低。本脚本把 4871 全量口径也算一遍，**两个口径并列输出，不做单一裁决**。

判定语义（与 `eval_bare.py:395` 完全一致）：`content.strip() in train_assistant_texts`
      —— 集合整段 strip 相等，不是模糊相似度。
产物限制：`rows[]` 只存 80 字 `head`，没有全文 ⇒ 对 head 只能做**前缀**命中
      （train_text.startswith(head)），语义是"前 80 字逐字相同"，仍是逐字证据但比整段相等弱一档。
      若产物里带全文（`text`/`content` 字段），自动走整段相等（`--field auto` 优先选全文）。

用法：
    CP=/c/ProgramData/anaconda3/python.exe
    $CP scripts/check_contam_v4.py --b logs/v4/eval-B/re60.json
    $CP scripts/check_contam_v4.py --b B.json --json logs/v4/contam-v4.json --verbose
    $CP scripts/check_contam_v4.py --selftest        # 2 正例 + 2 反例 = 4/4

纪律：只读产物与混料；不改 eval_*、不改产物、不写回任何数据。
"""
import argparse
import glob
import json
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MIX_4388 = os.path.join(ROOT, "data", "large-mix-plus", "train.jsonl")   # eval_bare 用的那个
MIX_4871 = os.path.join(ROOT, "tmp", "mix", "train-forge45.jsonl")       # v4 实际混料
HEAD_LEN = 80
PREVIEW_LEN = 400   # --dump-hits 里训练集原文预览长度（人工判"≥40 字连续重复"要够长才看得出）


def assistant_texts(path):
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            msgs = d.get("messages") or []
            if msgs:
                c = (msgs[-1] or {}).get("content") or ""
                if c.strip():
                    out.add(c.strip())
    return out


def row_texts(doc):
    """返回 [(i, cat, full_text_or_None, head_or_None)]"""
    src = doc.get("re_detail") or []
    rows = doc.get("rows") or []
    meta = {}
    for r in src:
        if r.get("i") is not None:
            meta[int(r["i"])] = r.get("cat")
    out = []
    for r in rows:
        i = int(r["i"])
        full = None
        for k in ("text", "content", "answer"):
            v = r.get(k)
            if isinstance(v, str) and v.strip():
                full = v
                break
        head = r.get("head") if isinstance(r.get("head"), str) else None
        out.append((i, meta.get(i, r.get("cat")), full, head))
    return out


def sha16(s):
    """训练侧文本的短指纹（用于"命中是否落在增量行"的跨层判定，避免把全文写进 JSON）"""
    import hashlib
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def calibre(rows, train_set, mode):
    """mode: 'exact'（整段相等）/ 'prefix'（前 80 字逐字相同）"""
    hits = []
    for i, cat, full, head in rows:
        if mode == "exact":
            if full is None:
                continue
            if full.strip() in train_set:
                hits.append({"i": i, "cat": cat, "how": "exact", "preview": full.strip()[:30],
                             "probe_len": len(full.strip()), "train_preview": full.strip()[:200],
                             "train_sha16": sha16(full.strip()),
                             "max_run": len(full.strip()), "max_run_of": len(full.strip())})
        else:
            if head is None:
                continue
            h = head.strip()
            if not h:
                continue
            for t in train_set:
                if t.startswith(h):
                    hits.append({"i": i, "cat": cat, "how": "prefix80", "preview": h[:30],
                                 "probe_len": len(h), "train_preview": t[:PREVIEW_LEN],
                                 "train_sha16": sha16(t),
                                 "max_run": lcs_len(h, t), "max_run_of": len(h)})
                    break
    return hits


def lcs_len(a, b):
    """最长连续公共子串长度（difflib，stdlib）——抽检判据 max_run。

    prefix 模式下 probe 只有 80 字，故 max_run 上限 80，只能读作**下界**。
    """
    if not a or not b:
        return 0
    from difflib import SequenceMatcher
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size


def pick_mode(rows, want):
    if want in ("exact", "prefix"):
        return want
    has_full = any(f is not None for _, _, f, _ in rows)
    return "exact" if has_full else "prefix"


def run(a):
    doc = json.load(open(a.b, encoding="utf-8"))
    rows = row_texts(doc)
    n = len(rows)
    mode = pick_mode(rows, a.field)
    print("=" * 78)
    print(f"[in] 产物 = {a.b}")
    print(f"[in] suite={doc.get('suite')} rows={n} data_sha16={((doc.get('data') or {}).get('sha16'))}")
    print(f"[mode] {mode}" + ("（整段 strip 相等，同 eval_bare:395）" if mode == "exact"
                              else f"（产物无全文，只能前 {HEAD_LEN} 字前缀命中）"))
    cals = {}
    for label, path in (("4388", a.mix4388), ("4871", a.mix4871)):
        if not os.path.isfile(path):
            print(f"[miss] {label} 口径比对集不存在：{path} → 该口径 NOT_MEASURED")
            cals[label] = None
            continue
        ts = assistant_texts(path)
        hits = calibre(rows, ts, mode)
        cals[label] = {"path": path, "train_n": len(ts), "hits": hits, "n": n}
        print(f"[contam] {label} 口径（{os.path.basename(path)}，{len(ts)} 条 assistant）"
              f" = {len(hits)}/{n}")
    # 与产物自带 contaminated 的一致性（自证语义对齐）
    own = [int(r["i"]) for r in (doc.get("re_detail") or []) if r.get("contaminated")]
    print(f"[own] 产物自带 contaminated = {len(own)}/{n}" + (f"（i={own}）" if own else ""))
    for label, c in cals.items():
        if c is None:
            continue
        hit_i = sorted(h["i"] for h in c["hits"])
        same = hit_i == sorted(own) if mode == "exact" else None
        print(f"[cmp] {label} 命中题号 = {hit_i}" + ("" if same is None else f" 与自带一致={same}"))
        for h in c["hits"]:
            print(f"  [hit] {label} i={h['i']:<3d} cat={h['cat']:<20s} how={h['how']:<9s} 前30字={h['preview']}")
    if a.verbose:
        by_cat = {}
        for label, c in cals.items():
            if c is None:
                continue
            d = {}
            for h in c["hits"]:
                d[h["cat"]] = d.get(h["cat"], 0) + 1
            by_cat[label] = d
        print(f"[by_cat] {json.dumps(by_cat, ensure_ascii=False)}")
    print("-" * 78)
    print("[VERDICT] 两口径并列，不做单一裁决："
          + " · ".join(f"{k}={len(v['hits'])}/{v['n']}" for k, v in cals.items() if v)
          + f"（{mode} 口径；4388 为 eval_bare 下界，4871 为 v4 全量；"
            "对 op-syntax/decision-chain 两者都偏低）")
    if a.dump_hits:
        outp = a.dump_hits
        with open(outp, "w", encoding="utf-8") as f:
            k = 0
            for label, c in cals.items():
                if c is None:
                    continue
                for h in c["hits"]:
                    f.write(json.dumps({"calibre": label, **h}, ensure_ascii=False) + "\n")
                    k += 1
        print(f"[dump] 抽检清单 → {outp}（{k} 条；含 head / 训练集前 {PREVIEW_LEN} 字 / max_run）")
        if mode != "exact":
            print("[dump][注意] 当前是 prefix 口径：max_run 上限=80（head 长度）⇒ max_run<40 只说明"
                  "『头 80 字内没有 40 字连续重复』，要判 ≥40 字必须重跑该题取全文")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"b": a.b, "mode": mode, "n": n, "own": own, "calibres": cals,
                       "note": "4388=eval_bare 硬编码；4871=v4 实际混料；两者均为逐字口径的下界；"
                               "prefix80 的偏倚方向是虚高（固定开头会伪命中）"},
                      f, ensure_ascii=False, indent=1)
        back = json.load(open(a.json, encoding="utf-8"))
        print(f"[ok] 报告 → {a.json}（回读 n={back['n']} 一致）")
    return 0


# ------------------------------------------------------------------ selftest
def run_selftest():
    print("== check_contam_v4 --selftest（2 正例 + 2 反例）==")
    tmpdir = tempfile.mkdtemp(prefix="_contam_selftest_", dir=os.path.join(ROOT, "logs", "v4"))
    train_path = os.path.join(tmpdir, "train.jsonl")
    verbatim = "先跑 kitty_die 确认壳，再在 .text 里定位特征串；这一步只看静态证据，不要动态附加。"
    other = "第二步对着 op-syntax 把参数补全：kitty_sym resolve 出 VA 之后再下断点，别跳步。"
    with open(train_path, "w", encoding="utf-8") as f:
        for t in (verbatim, other):
            f.write(json.dumps({"messages": [{"role": "user", "content": "q"},
                                             {"role": "assistant", "content": t}],
                                "meta": {"g": "selftest"}}, ensure_ascii=False) + "\n")
    rephrased = "先拿 kitty_die 看壳，再从 .text 段找特征串；这步只做静态取证，不做动态附加。"  # 改写（≠ 原文）
    unrelated = "今天天气不错，适合出门散步，顺便买杯咖啡。"
    rows = [
        {"i": 1, "cat": "re-op-syntax", "text": verbatim, "head": verbatim[:HEAD_LEN]},      # 正例①：整段抄
        {"i": 2, "cat": "re-op-syntax", "head": other[:HEAD_LEN]},                            # 正例②：只有 head，前 80 字抄
        {"i": 3, "cat": "re-decision-chain", "text": rephrased, "head": rephrased[:HEAD_LEN]},# 反例①：改写
        {"i": 4, "cat": "re-decision-chain", "text": unrelated, "head": unrelated[:HEAD_LEN]},# 反例②：无关
    ]
    prod = os.path.join(tmpdir, "b.json")
    json.dump({"suite": "selftest", "data": {"sha16": "selftest"}, "rows": rows,
               "re_detail": [{"i": r["i"], "cat": r["cat"], "pass": True,
                              "contaminated": False} for r in rows]},
              open(prod, "w", encoding="utf-8"), ensure_ascii=False)
    ts = assistant_texts(train_path)
    by_i = {r["i"]: r for r in rows}
    checks = []

    def chk(label, got, want):
        ok = got == want
        checks.append(ok)
        print(f"  {label:<34s} got={got!s:<6s} want={want!s:<6s} -> {'PASS' if ok else 'FAIL'}")

    # ① 整段相等语义（同 eval_bare:395）
    chk("① 整段抄训练集原文 → 命中", (by_i[1]["text"].strip() in ts), True)
    # ② 改写 → 不命中
    chk("② 改写文本 → 不命中", (by_i[3]["text"].strip() in ts), False)
    # ③ head 前缀语义
    h2 = by_i[2]["head"].strip()
    chk("③ head 前 80 字命中", any(t.startswith(h2) for t in ts), True)
    # ④ 无关文本 → 不命中
    h4 = by_i[4]["head"].strip()
    chk("④ 无关文本 → 不命中", any(t.startswith(h4) for t in ts), False)

    # 顺带跑一遍真实 CLI 路径（prefix 模式：只有 head 的行）
    rows_prefix = [r for r in rows if r["i"] in (2, 4)]
    json.dump({"suite": "selftest2", "data": {"sha16": "x"}, "rows": rows_prefix,
               "re_detail": [{"i": r["i"], "cat": r["cat"], "contaminated": False} for r in rows_prefix]},
              open(prod, "w", encoding="utf-8"), ensure_ascii=False)
    doc = json.load(open(prod, encoding="utf-8"))
    rr = row_texts(doc)
    hits = calibre(rr, ts, "prefix")
    chk("⑤ prefix 模式只命中 i=2", sorted(h["i"] for h in hits), [2])

    # ⑥ answers sidecar 的 exact 模式（整段 strip 相等；不是前缀）
    scpath = os.path.join(tmpdir, "refusal-100.answers.jsonl")
    with open(scpath, "w", encoding="utf-8") as f:
        f.write(json.dumps({"i": 1, "prompt": "抄原文的那条", "text": verbatim}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"i": 2, "prompt": "改写的那条", "text": rephrased}, ensure_ascii=False) + "\n")
    arows = answers_rows(scpath)
    ah = calibre(arows, ts, "exact")
    chk("⑥ answers exact 只命中 i=1（改写不中）", sorted(h["i"] for h in ah), [1])
    am = answers_measure(scpath, ts, ts, set())
    chk("⑥b answers_measure mode=exact", am["mode"], "exact")
    chk("⑥c answers 计 1/1（两口径同源时）", (am["c4388"], am["c4871"]), (1, 1))
    print(f"SELFTEST: {sum(checks)}/{len(checks)} ALL PASS" if all(checks)
          else f"SELFTEST: {sum(checks)}/{len(checks)} FAILED")
    # 不留垃圾：selftest 的临时目录用完即删（只删自己刚建的那个）
    try:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:
        pass
    return 0 if all(checks) else 1


# ------------------------------------------------------------------ all-suites
DEFAULT_SUITES = [
    ("re60",        os.path.join(ROOT, "logs", "base-only", "re60.json")),
    ("bench40",     os.path.join(ROOT, "logs", "base-only", "bench40.json")),
    ("kitty23",     os.path.join(ROOT, "logs", "base-only", "kitty23.json")),
    ("refusal-100", os.path.join(ROOT, "logs", "base-only", "refusal-100.json")),
]


def suite_measure(path, ts4388, ts4871, delta_sha, want_field):
    """单套测量 → dict（measurable=False 时 reason 说明为什么跑不了，照样出表，不隐藏）"""
    name = os.path.splitext(os.path.basename(path))[0]
    out = {"suite": name, "path": path, "measurable": False, "reason": "", "mode": None,
           "n": 0, "c4388": None, "c4871": None, "diff": None, "verdict": "n/a",
           "extra_i": [], "own_contaminated": None}
    if not os.path.isfile(path):
        out["reason"] = "产物不存在"
        return out
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        out["reason"] = f"JSON 解析失败：{e}"
        return out
    rows = row_texts(doc)
    out["n"] = len(rows)
    out["own_contaminated"] = sum(1 for r in (doc.get("re_detail") or []) if r.get("contaminated"))
    if not rows:
        out["reason"] = ("无 rows[]（顶层键=" + ",".join(sorted(doc.keys()))
                         + "）→ 无逐题文本，整段/前缀比对均不可跑")
        return out
    mode = pick_mode(rows, want_field)
    out["mode"] = mode
    h4388 = calibre(rows, ts4388, mode)
    h4871 = calibre(rows, ts4871, mode)
    out["c4388"], out["c4871"] = len(h4388), len(h4871)
    out["diff"] = len(h4871) - len(h4388)
    i4388 = {h["i"] for h in h4388}
    extra = [h for h in h4871 if h["i"] not in i4388]
    out["extra_i"] = sorted(h["i"] for h in extra)
    out["measurable"] = True
    if out["diff"] == 0:
        out["verdict"] = "same"
    elif extra and all(h.get("train_sha16") in delta_sha for h in extra):
        out["verdict"] = "forge-only"
    else:
        out["verdict"] = "unknown"
    return out


def answers_rows(path):
    """读 sidecar（每行带全文 text）→ [(i, cat, text, None)]

    sidecar 是 eval 侧落盘的逐题答案**全文**（不是产物 rows[] 里的 80 字 head），
    所以这里能做**整段 strip 相等**判定（mode=exact），与三套产物的 prefix80 区分开。
    """
    rows, n = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                d = json.loads(line)
            except Exception:
                continue
            i = d.get("i", d.get("idx", n))
            try:
                i = int(i)
            except Exception:
                i = n
            txt = None
            for k in ("text", "answer", "response", "content"):
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    txt = v
                    break
            if txt:
                rows.append((i, d.get("cat"), txt, None))
    return rows


def answers_measure(path, ts4388, ts4871, delta_sha):
    """sidecar 单套测量：mode 固定 exact（整段 strip 相等，不是前缀）"""
    out = {"suite": "refusal-100(answers)", "path": path, "measurable": False, "reason": "",
           "mode": "exact", "n": 0, "c4388": None, "c4871": None, "diff": None,
           "verdict": "n/a", "extra_i": [], "own_contaminated": None, "hits": []}
    if not path or not os.path.isfile(path):
        out["reason"] = "sidecar 不存在（未传 --answers-jsonl 且未自动发现）"
        return out
    rows = answers_rows(path)
    out["n"] = len(rows)
    if not rows:
        out["reason"] = "sidecar 无可判文本（每行缺 text/answer/response）"
        return out
    # prompt 侧栏（命中样例要打 prompt 前 30 字，不是 text 前 30 字）
    pid = {}
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate((x for x in f if x.strip()), 1):
            try:
                d = json.loads(line)
            except Exception:
                continue
            k = d.get("i", d.get("idx", n))
            try:
                k = int(k)
            except Exception:
                k = n
            pid[k] = (d.get("prompt") or d.get("q") or "")[:30]
    h4388 = calibre(rows, ts4388, "exact")
    h4871 = calibre(rows, ts4871, "exact")
    out["c4388"], out["c4871"] = len(h4388), len(h4871)
    out["diff"] = len(h4871) - len(h4388)
    i4388 = {h["i"] for h in h4388}
    extra = [h for h in h4871 if h["i"] not in i4388]
    out["extra_i"] = sorted(h["i"] for h in extra)
    out["hits"] = h4871 if len(h4871) >= len(h4388) else h4388
    for h in out["hits"]:
        h["prompt30"] = pid.get(h["i"], "")
    out["measurable"] = True
    if out["diff"] == 0:
        out["verdict"] = "same"
    elif extra and all(h.get("train_sha16") in delta_sha for h in extra):
        out["verdict"] = "forge-only"
    else:
        out["verdict"] = "unknown"
    return out


def find_answers_sidecar(suites):
    """自动发现 sidecar：refusal 产物同目录的 *.answers.jsonl"""
    dirs = []
    for _, p in suites:
        d = os.path.dirname(os.path.abspath(p))
        if d not in dirs:
            dirs.append(d)
    for d in dirs + [os.path.join(ROOT, "logs", "base-only")]:
        for nm in ("refusal-100.answers.jsonl", "refusal.answers.jsonl"):
            p = os.path.join(d, nm)
            if os.path.isfile(p):
                return p
        cand = sorted(glob.glob(os.path.join(d, "*.answers.jsonl")))
        if cand:
            return cand[0]
    return ""


def run_all_suites(a):
    if a.suites:
        suites = [(os.path.splitext(os.path.basename(p))[0], p) for p in a.suites.split(",") if p.strip()]
    else:
        suites = DEFAULT_SUITES
    ts4388 = assistant_texts(a.mix4388) if os.path.isfile(a.mix4388) else set()
    ts4871 = assistant_texts(a.mix4871) if os.path.isfile(a.mix4871) else set()
    delta_sha = {sha16(t) for t in (ts4871 - ts4388)}
    print("=" * 96)
    print(f"[mix] 4388 口径 {os.path.basename(a.mix4388)} = {len(ts4388)} 条 · "
          f"4871 口径 {os.path.basename(a.mix4871)} = {len(ts4871)} 条 · 增量唯一文本 = {len(delta_sha)} 条")
    print(f"[mix] 增量指纹集（跨层判定用）= {len(delta_sha)} 个 sha16")
    print("-" * 96)
    print(f"{'suite':<22s}{'mode':<10s}{'contam(4388)':>13s}{'contam(4871)':>13s}{'diff':>7s}   cross-layer")
    results = []
    for name, path in suites:
        r = suite_measure(path, ts4388, ts4871, delta_sha, a.field)
        results.append(r)
        if not r["measurable"]:
            print(f"{name:<22s}{str(r['mode'] or '--'):<10s}{'--':>13s}{'--':>13s}{'--':>7s}   n/a（{r['reason']}）")
        else:
            print(f"{name:<22s}{r['mode']:<10s}{r['c4388']:>13d}{r['c4871']:>13d}{r['diff']:>+7d}   {r['verdict']}"
                  + (f"（多出 i={r['extra_i']}）" if r["extra_i"] else "")
                  + f"  [n={r['n']}, 自带 contaminated={r['own_contaminated']}]")
    # sidecar（答案级污染）：refusal 侧只有 sidecar 有全文 → 只有这一套能做 exact
    apath = a.answers_jsonl or find_answers_sidecar(suites)
    ra = answers_measure(apath, ts4388, ts4871, delta_sha) if apath else None
    if ra is not None:
        results.append(ra)
        if not ra["measurable"]:
            print(f"{ra['suite']:<22s}{'exact':<10s}{'--':>13s}{'--':>13s}{'--':>7s}   n/a（{ra['reason']}）")
        else:
            print(f"{ra['suite']:<22s}{'exact':<10s}{ra['c4388']:>13d}{ra['c4871']:>13d}{ra['diff']:>+7d}   {ra['verdict']}"
                  + (f"（多出 i={ra['extra_i']}）" if ra["extra_i"] else "")
                  + f"  [n={ra['n']}, 整段 strip 相等]")
            for h in ra["hits"][:10]:
                print(f"  [hit] answers i={h['i']:<3d} prompt30={h.get('prompt30') or h['preview']!r} "
                      f"train200={h['train_preview'][:60]}… max_run={h['max_run']}/{h['max_run_of']}")
    print("-" * 96)
    ok = [r for r in results if r["measurable"]]
    na = [r for r in results if not r["measurable"]]
    tot4388 = sum(r["c4388"] for r in ok)
    tot4871 = sum(r["c4871"] for r in ok)
    vc = {}
    for r in ok:
        vc[r["verdict"]] = vc.get(r["verdict"], 0) + 1
    cross = " · ".join(f"{k}×{v}" for k, v in sorted(vc.items())) or "无可测套"
    if na:
        cross += f" · 不可测×{len(na)}（{','.join(r['suite'] for r in na)}）"
    print(f"[CONTAM-ALL] 合计 4388={tot4388} · 4871={tot4871} · 跨层={cross}")
    print("[CONTAM-ALL][口径] 产物三套 = prefix80（宽松，固定开头会虚高）；"
          "answers sidecar = **exact**（整段 strip 相等，严格）；两口径不可直接互比")
    print("[CONTAM-ALL][口径] 逐字/前缀口径都是下界；差值>0 且判定 forge-only = 多出来的命中"
          "全落在 4871 的增量行（99 条新文本）")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"mix": {"4388": len(ts4388), "4871": len(ts4871), "delta_uniq": len(delta_sha)},
                       "suites": results,
                       "total": {"contam4388": tot4388, "contam4871": tot4871, "cross": vc}},
                      f, ensure_ascii=False, indent=1)
        back = json.load(open(a.json, encoding="utf-8"))
        print(f"[ok] 汇总 → {a.json}（回读 {len(back['suites'])} 套）")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(description="contaminated 的 v4 口径离线复算（只读）")
    ap.add_argument("--b", default=os.path.join(ROOT, "logs", "base-only", "re60.json"))
    ap.add_argument("--field", default="auto", choices=["auto", "exact", "prefix"],
                    help="auto=有全文走整段相等，否则前 80 字前缀")
    ap.add_argument("--mix4388", default=MIX_4388, help="eval_bare 硬编码的比对集")
    ap.add_argument("--mix4871", default=MIX_4871, help="v4 实际混料")
    ap.add_argument("--json", default="")
    ap.add_argument("--dump-hits", default="",
                    help="把命中题导出 jsonl（head + 训练集命中条前 200 字 + max_run），供 ≥2 条差值的抽检")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--all-suites", action="store_true",
                    help="B 组四套（re60/bench40/kitty23/refusal-100）各跑一次，出汇总表")
    ap.add_argument("--suites", default="",
                    help="配合 --all-suites 指定逗号分隔的产物路径（缺省用 logs/base-only 四套）")
    ap.add_argument("--answers-jsonl", default="",
                    help="refusal 侧 sidecar（每行带全文 text）→ 做 mode=exact 的答案级污染判定；"
                         "缺省时 --all-suites 会自动发现同目录 *.answers.jsonl")
    a = ap.parse_args(argv)
    if a.selftest:
        return run_selftest()
    if a.all_suites:
        return run_all_suites(a)
    if not os.path.isfile(a.b):
        print(f"[FATAL] 产物不存在：{a.b}", file=sys.stderr)
        return 2
    return run(a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
