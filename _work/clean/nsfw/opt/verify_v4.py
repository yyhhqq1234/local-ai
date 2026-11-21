# -*- coding: utf-8 -*-
"""verify_v4.py — 三件套产物校验 + 统计（只读，结果打印到 stdout）。"""
import io
import json
import os
import sys
from collections import Counter

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
sys.path.insert(0, os.path.join(ROOT, "_work", "clean", "nsfw", "opt"))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "_shared", "scripts"))
import opt_common as C  # noqa: E402  （导入 common 时已把 stdout 设为 UTF-8）

OPT = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated", "cleaned", "opt")
SYS = C.SYS_PERMIT
FILES = ["nsfw-zeroshot-v4.jsonl", "nsfw-continue-v4.jsonl", "nsfw-frontload-v4.jsonl"]


def load(p):
    out = []
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def strict(t):
    return C.strict_count(t)


old = load(os.path.join(OPT, "nsfw-zeroshot.jsonl"))
old_norm = {C.common.norm_text(o["messages"][-1]["content"]) for o in old}

all_rows = {}
for fn in FILES:
    all_rows[fn] = load(os.path.join(OPT, fn))

print("=== 行数 / 唯一性")
seen_global = {}
for fn in FILES:
    rows = all_rows[fn]
    asst = [r["messages"][-1]["content"] for r in rows]
    print("%-26s rows=%d uniq=%d uniq_norm=%d sys_verbatim=%s"
          % (fn, len(rows), len(set(asst)), len({C.common.norm_text(a) for a in asst}),
             all(r["messages"][0]["content"] == SYS for r in rows)))
    for a in asst:
        seen_global.setdefault(C.common.norm_text(a), []).append(fn)
dups = {k: v for k, v in seen_global.items() if len(set(v)) > 1}
print("跨文件 assistant 重复:", len(dups))

print("\n=== 前 300 字 strict 分布")
for fn in FILES:
    rows = all_rows[fn]
    v = sorted(strict(r["messages"][-1]["content"][:300]) for r in rows)
    n = len(v)
    print("%-26s n=%d mean=%.2f med=%d p10=%d p90=%d ≥3=%.1f%% ≥5=%.1f%% ≥8=%.1f%%"
          % (fn, n, sum(v) / n, v[n // 2], v[n // 10], v[n * 9 // 10],
             100.0 * sum(1 for x in v if x >= 3) / n,
             100.0 * sum(1 for x in v if x >= 5) / n,
             100.0 * sum(1 for x in v if x >= 8) / n))

print("\n=== 与旧 800 行零起点集重合")
for fn in FILES:
    rows = all_rows[fn]
    asst = [r["messages"][-1]["content"] for r in rows]
    hit = sum(1 for a in asst if C.common.norm_text(a) in old_norm)
    print("%-26s exact_norm_overlap=%d/%d=%.2f%%" % (fn, hit, len(asst),
                                                     100.0 * hit / len(asst)))

print("\n=== B 切分一致性")
rows = all_rows["nsfw-continue-v4.jsonl"]
bad = pre_min = pre_max = 0
prels = []
prestrict = []
SRC = [os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated", "cleaned",
                    "nsfw-clean.jsonl"),
       os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated", "gate-pos.jsonl"),
       os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data", "nsfw-gated",
                    "train-2b-gated-v5.jsonl")]
src_norm = set()
DECL2 = "（说明：本篇角色均为成年人，年龄均已满18岁。）"
for p in SRC:
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            k = C.common.norm_text(C.assistant_of(o).strip())
            if k:
                src_norm.add(k)
                src_norm.add(k + C.common.norm_text(DECL2))   # 允许成年声明追加
recon_ok = 0
for r in rows:
    u, a = r["messages"][1]["content"], r["messages"][2]["content"]
    sep = "：\n\n"
    if sep not in u:
        bad += 1
        continue
    pre = u.split(sep, 1)[1]
    prels.append(len(pre))
    prestrict.append(strict(pre))
    if not (80 <= len(pre) <= 200):
        pre_min += 1
    if len(a) < 200:
        pre_max += 1
    if C.common.norm_text(pre + a) in src_norm:
        recon_ok += 1
print("rows=%d sep_missing=%d pre_len_out_of_range=%d suffix<200=%d recon_in_src=%d/%d"
      % (len(rows), bad, pre_min, pre_max, recon_ok, len(rows)))
print("pre_len med=%d min=%d max=%d | pre_strict min=%d ≥2=%.1f%%"
      % (sorted(prels)[len(prels) // 2], min(prels), max(prels), min(prestrict),
         100.0 * sum(1 for x in prestrict if x >= 2) / len(prestrict)))

# 逐行验证 pre+suf == 源正文（用 ledger 的 sha 反查池子太重，这里只验切分自身完整）
# 逻辑：assistant = 源正文第 p 字之后；无法从文件独立还原，故校验 pre 结尾是句末标点
SENT_END = "。！？；\n"
bad_end = sum(1 for r in rows
              if r["messages"][1]["content"].split("：\n\n", 1)[-1][-1:] not in SENT_END)
print("pre 非句末结尾的行:", bad_end)

print("\n=== A 用户形态 / 100 字承诺")
rows = all_rows["nsfw-zeroshot-v4.jsonl"]
cnt = Counter(r["messages"][1]["content"] for r in rows)
print("distinct user 说法:", len(cnt))
explicit = sum(v for k, v in cnt.items() if "100 字" in k or "第一段就" in k
               or "直接从身体" in k or "开头就写身体" in k)
print("显式「开头就进」类: %d / %d = %.1f%%" % (explicit, len(rows), 100.0 * explicit / len(rows)))
claim = [r for r in rows if ("100 字内" in r["messages"][1]["content"]
                             or "前 100 字" in r["messages"][1]["content"])]
viol = sum(1 for r in claim if strict(r["messages"][-1]["content"][:100]) < 2)
print("带 100 字承诺行: %d，其中前 100 字 <2 strict: %d" % (len(claim), viol))
for k, v in cnt.most_common():
    print("   %4d  %s" % (v, k[:60]))

print("\n=== C 用户形态")
rows = all_rows["nsfw-frontload-v4.jsonl"]
cnt = Counter(r["messages"][1]["content"] for r in rows)
print("distinct user 说法:", len(cnt))
for k, v in cnt.most_common():
    print("   %4d  %s" % (v, k[:60]))

print("\n=== 成年声明追加统计（正文尾部括号声明）")
DECL = "（说明：本篇角色均为成年人，年龄均已满18岁。）"
for fn in FILES:
    rows = all_rows[fn]
    n = sum(1 for r in rows if r["messages"][-1]["content"].endswith(DECL))
    print("%-26s decl_tail=%d/%d=%.1f%%" % (fn, n, len(rows), 100.0 * n / len(rows)))

print("\n=== 长度")
for fn in FILES:
    L = sorted(len(r["messages"][-1]["content"]) for r in all_rows[fn])
    print("%-26s med=%d min=%d max=%d" % (fn, L[len(L) // 2], L[0], L[-1]))
