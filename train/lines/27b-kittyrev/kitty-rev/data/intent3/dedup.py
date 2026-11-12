#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data/intent3/dedup.py — 数据集隔离门禁（full-hash / user-hash / 字符 5-gram Jaccard）

单文件自检:
  python dedup.py --a data/intent3/re-sft.jsonl
双文件交叉:
  python dedup.py --a data/intent3/re-sft.jsonl --b train/lines/27b-kittyrev/kitty-rev/data/large-mix-plus.jsonl
  python dedup.py --a A.jsonl --b B.jsonl --json logs/isolation-AB.json
长度分布:
  python dedup.py --a data/intent3/re-sft.jsonl --stats

退出码: 0 通过（无重复、无超阈对）; 1 有重复或超阈; 2 输入/参数错误

字段约定（按序探测，可用 --text-field/--user-field 覆盖，逗号分隔）:
  text: response, text, content, answer, completion, assistant
  user: prompt, user, question, query, instruction
每条记录必须能取出 text；取不到即报错（不静默跳过）。
"""
import argparse
import hashlib
import json
import statistics
import sys
import unicodedata

NGRAM = 5
DEFAULT_THRESHOLD = 0.35
TEXT_FIELDS = ["response", "text", "content", "answer", "completion", "assistant"]
USER_FIELDS = ["prompt", "user", "question", "query", "instruction"]


def die(msg, code=2):
    print(f"[dedup] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_jsonl(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    die(f"{path}:{i} JSON 解析失败: {e}")
                if not isinstance(obj, dict):
                    die(f"{path}:{i} 不是 JSON 对象")
                rows.append(obj)
    except OSError as e:
        die(f"打不开 {path}: {e}")
    return rows


def pick(obj, fields):
    for k in fields:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def normalize(s):
    """NFKC + 小写 + 去空白/标点/符号，只留字母、数字、CJK 与组合符。"""
    s = unicodedata.normalize("NFKC", s).lower()
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N", "M"):
            out.append(ch)
    return "".join(out)


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def ngrams(s, n=NGRAM):
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def jaccard(a, b):
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def text_of(row, tfields):
    t = pick(row, tfields)
    if t is not None:
        return t
    msgs = row.get("messages")
    if isinstance(msgs, list):
        parts = [m.get("content") for m in msgs
                 if isinstance(m, dict) and isinstance(m.get("content"), str)]
        if parts:
            return "\n".join(parts)
    die(f"记录缺少文本字段（试过 {tfields} + messages）: {json.dumps(row, ensure_ascii=False)[:120]}")


def user_of(row, ufields):
    u = pick(row, ufields)
    if u is not None:
        return u
    msgs = row.get("messages")
    if isinstance(msgs, list):
        for m in msgs:
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                return m["content"]
    return None


def length_stats(rows, tfields):
    lens = sorted(len(text_of(r, tfields)) for r in rows)
    n = len(lens)
    if n == 0:
        return {}
    hist = {"<160": 0, "160-199": 0, "200-299": 0, "300-399": 0, "400-499": 0, ">=500": 0}
    for L in lens:
        if L < 160:
            hist["<160"] += 1
        elif L < 200:
            hist["160-199"] += 1
        elif L < 300:
            hist["200-299"] += 1
        elif L < 400:
            hist["300-399"] += 1
        elif L < 500:
            hist["400-499"] += 1
        else:
            hist[">=500"] += 1
    p90 = lens[min(n - 1, int(round(0.9 * (n - 1))))]
    return {
        "count": n,
        "min": lens[0],
        "max": lens[-1],
        "mean": round(sum(lens) / n, 1),
        "median": statistics.median(lens),
        "p90": p90,
        "histogram": hist,
    }


def self_check(rows, threshold, tfields, ufields):
    texts = [normalize(text_of(r, tfields)) for r in rows]
    full = [sha256(t) for t in texts]

    full_groups = {}
    for i, h in enumerate(full):
        full_groups.setdefault(h, []).append(i)
    full_dups = {h: idx for h, idx in full_groups.items() if len(idx) > 1}

    user_groups = {}
    for i, r in enumerate(rows):
        u = user_of(r, ufields)
        if u is not None:
            user_groups.setdefault(sha256(normalize(u)), []).append(i)
    user_dups = {h: idx for h, idx in user_groups.items() if len(idx) > 1}

    grams = [ngrams(t) for t in texts]
    lens = [len(g) for g in grams]
    pairs = []
    max_j, max_pair = 0.0, None
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if min(lens[i], lens[j]) < threshold * max(lens[i], lens[j]):
                continue
            jv = jaccard(grams[i], grams[j])
            if jv > max_j:
                max_j, max_pair = jv, (i, j)
            if jv >= threshold:
                pairs.append({"a": i, "b": j, "jaccard": round(jv, 4)})
    pairs.sort(key=lambda p: -p["jaccard"])
    return {
        "records": len(rows),
        "full_hash_duplicates": sum(len(v) for v in full_dups.values()),
        "full_hash_duplicate_groups": [
            {"indices": v, "ids": [rows[i].get("id") for i in v]} for v in full_dups.values()
        ],
        "user_hash_duplicates": sum(len(v) for v in user_dups.values()),
        "user_hash_duplicate_groups": [
            {"indices": v, "ids": [rows[i].get("id") for i in v]} for v in user_dups.values()
        ],
        "jaccard_threshold": threshold,
        "jaccard_max": round(max_j, 4),
        "jaccard_max_pair": (
            {"a": max_pair[0], "b": max_pair[1],
             "ids": [rows[max_pair[0]].get("id"), rows[max_pair[1]].get("id")]}
            if max_pair else None
        ),
        "pairs_over_threshold": len(pairs),
        "top_pairs": pairs[:20],
    }


def cross_check(rows_a, rows_b, threshold, tfields, ufields):
    ta = [normalize(text_of(r, tfields)) for r in rows_a]
    tb = [normalize(text_of(r, tfields)) for r in rows_b]
    full_a = {sha256(t) for t in ta}
    full_b = {sha256(t) for t in tb}
    user_a = {sha256(normalize(u)) for u in (user_of(r, ufields) for r in rows_a) if u}
    user_b = {sha256(normalize(u)) for u in (user_of(r, ufields) for r in rows_b) if u}
    grams_a = [ngrams(t) for t in ta]
    grams_b = [ngrams(t) for t in tb]
    la = [len(g) for g in grams_a]
    lb = [len(g) for g in grams_b]
    max_j, max_pair, over = 0.0, None, 0
    for i in range(len(rows_a)):
        for j in range(len(rows_b)):
            if min(la[i], lb[j]) < threshold * max(la[i], lb[j]):
                continue
            jv = jaccard(grams_a[i], grams_b[j])
            if jv > max_j:
                max_j, max_pair = jv, (i, j)
            if jv >= threshold:
                over += 1
    return {
        "a_records": len(rows_a),
        "b_records": len(rows_b),
        "full_hash_intersection": len(full_a & full_b),
        "user_hash_intersection": len(user_a & user_b),
        "jaccard_threshold": threshold,
        "jaccard_max": round(max_j, 4),
        "jaccard_max_pair": (
            {"a_id": rows_a[max_pair[0]].get("id"), "b_id": rows_b[max_pair[1]].get("id")}
            if max_pair else None
        ),
        "pairs_over_threshold": over,
    }


def main():
    ap = argparse.ArgumentParser(description="full-hash / user-hash / 5-gram Jaccard 隔离门禁")
    ap.add_argument("--a", required=True, help="主 jsonl")
    ap.add_argument("--b", help="对照 jsonl（给出即做交叉检查）")
    ap.add_argument("--json", help="把完整报告写到该路径")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Jaccard 阈值，默认 0.35")
    ap.add_argument("--stats", action="store_true", help="只输出长度分布")
    ap.add_argument("--text-field", default=",".join(TEXT_FIELDS))
    ap.add_argument("--user-field", default=",".join(USER_FIELDS))
    args = ap.parse_args()

    tfields = [x.strip() for x in args.text_field.split(",") if x.strip()]
    ufields = [x.strip() for x in args.user_field.split(",") if x.strip()]
    rows_a = load_jsonl(args.a)
    ldist = length_stats(rows_a, tfields)

    if args.stats and not args.b:
        print(json.dumps({"file": args.a, "length": ldist}, ensure_ascii=False, indent=2))
        return 0

    report = {"a": args.a, "length": ldist,
              "self": self_check(rows_a, args.threshold, tfields, ufields)}
    if args.b:
        rows_b = load_jsonl(args.b)
        report["b"] = args.b
        report["b_length"] = length_stats(rows_b, tfields)
        report["cross"] = cross_check(rows_a, rows_b, args.threshold, tfields, ufields)

    ok = (
        report["self"]["full_hash_duplicates"] == 0
        and report["self"]["user_hash_duplicates"] == 0
        and report["self"]["pairs_over_threshold"] == 0
        and (not args.b or (report["cross"]["full_hash_intersection"] == 0
                            and report["cross"]["user_hash_intersection"] == 0
                            and report["cross"]["pairs_over_threshold"] == 0))
    )
    report["verdict"] = "PASS" if ok else "FAIL"

    if args.json:
        import os
        parent = os.path.dirname(os.path.abspath(args.json))
        os.makedirs(parent, exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    s = report["self"]
    print(f"[a] {args.a}: {s['records']} 条, len min/med/mean/p90/max = "
          f"{ldist['min']}/{ldist['median']}/{ldist['mean']}/{ldist['p90']}/{ldist['max']}")
    print(f"[a] full-hash dups={s['full_hash_duplicates']} user-hash dups={s['user_hash_duplicates']} "
          f"jaccard_max={s['jaccard_max']} pairs>={args.threshold}: {s['pairs_over_threshold']}")
    if s["top_pairs"]:
        print(f"[a] top pair: {s['top_pairs'][0]}")
    if args.b:
        c = report["cross"]
        print(f"[cross] {args.b}: full∩={c['full_hash_intersection']} user∩={c['user_hash_intersection']} "
              f"jaccard_max={c['jaccard_max']} pairs>={args.threshold}: {c['pairs_over_threshold']}")
    print(f"[verdict] {report['verdict']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
