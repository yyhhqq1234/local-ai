#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""clean_27b_data.py —— 27B 数据清洗（在 audit 结论上动手）

清洗规则（只做确定性动作，不动语义）：
  C1  删整行完全重复（保留首条）—— gen3_1p2 实测有 14,452 行重复（26.7%）
  C2  删 assistant 有效字符 < 20 的空壳行
  C3  删整行 > 16,000 字符的超长行（ctx=2048 训练时必然被截断，白占步数）
  C4  抹零宽字符 / U+FFFD 之外的软控制符（不删行，只净化文本）
  C5  按 user 文本归一化后，同一 user 在同一 cat 内只保留 1 条
      （跨 cat 的保留 —— 那是不同任务，不是重复）
  C6  可选：pos ×N 过采样（用于把 pos:neg 拉回 1:1，脚本不支持 sample weight 时用）

产出：
  <out>.jsonl          主清洗集（C1-C5）
  <out>x2.jsonl        主清洗集 + pos ×2（C6，若 --pos-repeat 2）
  每份带 .sha256；同时打印/写 stats md

用法：
  python clean_27b_data.py --src .../gen3_1p2-nsfw-kitty.jsonl --out .../gen3_1p3-nsfw-kitty.jsonl --pos-repeat 2
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ZW = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
WS = re.compile(r"\s+")
REFUSAL_PREFIX = "当前为常规模式（未授权成人向内容），不输出露骨性描写。"


def nkey(s):
    return hashlib.sha1(WS.sub("", s or "").encode("utf-8", "replace")).hexdigest()


def clean_text(s):
    if not isinstance(s, str):
        return s
    s = ZW.sub("", s)
    s = C0.sub("", s)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pos-repeat", type=int, default=2)
    ap.add_argument("--max-chars", type=int, default=16000)
    ap.add_argument("--min-asst", type=int, default=20)
    a = ap.parse_args()

    st = Counter()
    seen_row = set()
    seen_user_cat = set()
    out_rows = []
    cat_cnt = Counter()

    with open(a.src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                st["C0_empty"] += 1
                continue
            d = json.loads(line)
            st["in"] += 1

            # C4 文本净化
            msgs = d.get("messages") or []
            changed = False
            for m in msgs:
                c = m.get("content")
                c2 = clean_text(c)
                if c2 != c:
                    m["content"] = c2
                    changed = True
            if changed:
                st["C4_cleaned"] += 1
                d["messages"] = msgs

            raw = json.dumps(d, ensure_ascii=False)

            # C1 整行重复
            h = hashlib.sha1(raw.encode("utf-8")).hexdigest()
            if h in seen_row:
                st["C1_dup"] += 1
                continue
            seen_row.add(h)

            asst = [m for m in msgs if m.get("role") == "assistant"]
            atext = (asst[-1].get("content") or "") if asst else ""

            # C2 空壳
            if len(atext.strip()) < a.min_asst:
                st["C2_short"] += 1
                continue
            # C3 超长
            if len(raw) > a.max_chars:
                st["C3_long"] += 1
                continue

            # C5 同 user 同 cat 去重
            user = "\n".join(m.get("content", "") for m in msgs if m.get("role") == "user")
            cat = ((d.get("meta") or {}).get("cat") or "")
            k = (nkey(user), cat)
            if k in seen_user_cat:
                st["C5_dup_user_cat"] += 1
                continue
            seen_user_cat.add(k)

            out_rows.append(d)
            cat_cnt[cat or "?"] += 1

    os.makedirs(os.path.dirname(a.out), exist_ok=True)

    def dump(rows, path):
        with open(path, "w", encoding="utf-8", newline="\n") as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + "\n")
        h = hashlib.sha256(open(path, "rb").read()).hexdigest()
        open(path + ".sha256", "w").write(h + "\n")
        return h, os.path.getsize(path)

    h1, s1 = dump(out_rows, a.out)

    def ratio(rows):
        p = sum(1 for r in rows if "NSFW 许可" in (r["messages"][0].get("content") or ""))
        n = sum(1 for r in rows if ("常规" in (r["messages"][0].get("content") or "")
                                    and "NSFW 许可" not in (r["messages"][0].get("content") or "")))
        return p, n

    p1, n1 = ratio(out_rows)
    print(f"[主清洗集] {a.out}")
    print(f"  行 {len(out_rows)}（输入 {st['in']}）  pos {p1} / neg {n1} = 1 : {n1/max(1,p1):.3f}")
    print(f"  删除：整行重复 {st['C1_dup']} · 空壳 {st['C2_short']} · 超长 {st['C3_long']} "
          f"· 同user同cat重复 {st['C5_dup_user_cat']}")
    print(f"  净化行 {st['C4_cleaned']}   sha {h1[:16]}  {s1/1048576:.1f} MiB")
    print(f"  类别：{dict(cat_cnt.most_common(12))}")

    if a.pos_repeat > 1:
        pos = [r for r in out_rows if "NSFW 许可" in (r["messages"][0].get("content") or "")]
        rest = [r for r in out_rows if r not in pos] if False else \
               [r for r in out_rows if not ("NSFW 许可" in (r["messages"][0].get("content") or ""))]
        mixed = rest + pos * a.pos_repeat
        # 稳定打散（固定种子），避免同类扎堆
        import random
        random.Random(20261101).shuffle(mixed)
        out2 = a.out.replace(".jsonl", f"x{a.pos_repeat}.jsonl")
        h2, s2 = dump(mixed, out2)
        p2, n2 = ratio(mixed)
        print(f"[过采样集] {out2}")
        print(f"  行 {len(mixed)}  pos {p2} / neg {n2} = 1 : {n2/max(1,p2):.3f}"
              f"  sha {h2[:16]}  {s2/1048576:.1f} MiB")

    print(f"[done] {time.strftime('%H:%M:%S')}")


if __name__ == "__main__":
    sys.exit(main())
