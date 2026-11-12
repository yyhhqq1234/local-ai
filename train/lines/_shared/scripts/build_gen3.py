#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gen3.py —— GEN3 数据：v2 全量 + re-qc silver 真逆向样本合流（纯 CPU）

口径
  基线 = gen2-nsfw-kitty-v2.jsonl（46,281 条，已做过超长整族丢弃 / 门控成对回验）
  增量 = data/kitty-reverse/re-qc/silver.jsonl（8,815 条，真逆向质检通过样本）
  合流后重新做：内容级去重 → 超长丢弃 → kitty 类别标注 → 门控成对回验 → 工具名清点

去重键（任一命中即丢银样本，v2 永远优先保留）
  1) normalized_text : 全部 messages 的 content 去空白后拼接的 sha1
  2) _hash           : silver 自带的内容指纹
  3) _user_hash      : silver 自带的 user 指纹（与 v2 的 user 文本哈希对齐）

用法
  python train\\scripts\\build_gen3.py [--maxch 6000] [--dry]
  输出 train/lines/27b-kittyrev/data/versions/gen3-nsfw-kitty.<ts>.jsonl(+.sha256)
"""
import argparse
import hashlib
import json
import os
import re
import time
from collections import Counter

TRAIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(TRAIN, "data")
VERS = os.path.join(DATA, "versions")

SRC_V2 = os.path.join(VERS, "gen2-nsfw-kitty-v2.20261029-124315.jsonl")
SRC_SILVER = os.path.join(DATA, "kitty-reverse", "re-qc", "silver.jsonl")

TRIG = re.compile(r"^\s*(\[\[NSFW\]\]|\[NSFW\]|NSFW|成人内容|R18|18\+ ?模式?|无限制模式|"
                  r"成人向创作模式|\[\[模式:NSFW\]\])\s*[:：,，]?\s*", re.I)
CATS = ["real-trajectory", "op-syntax", "tool-route", "kb-re", "kb-tool"]
# 契约工具 64 个 + 4 个别名滥用（GEN2 已知），清点用
STRAY = {"kitty_cedump", "kitty_rea_", "kitty_v6", "reverse_add_"}


def text_of(o):
    return "\n".join(str(m.get("content", "")) for m in o.get("messages") or [])


def user_of(o):
    return next((str(m.get("content") or "") for m in o.get("messages") or []
                 if m.get("role") == "user"), "")


def norm(s):
    return re.sub(r"\s+", "", TRIG.sub("", s or "", count=1))


def sha(s):
    return hashlib.sha1(s.encode("utf-8", "replace")).hexdigest()


def load(path):
    rows = []
    if not os.path.exists(path):
        raise SystemExit(f"[FATAL] 缺文件 {path}")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def tag_kitty(o):
    """按内容给 kitty 行打类别（与 train_kitty.py REQUIRED_CATS 同口径）"""
    a = "\n".join(str(m.get("content", "")) for m in o.get("messages") or []
                  if m.get("role") == "assistant")
    meta = o.setdefault("meta", {})
    if "kitty_" in a:
        cat = "tool-route"
    elif re.search(r"\bop=|action=|AL_|SELECT_|MODENUM", a):
        cat = "op-syntax"
    elif re.search(r"坑|砟|判据|复盘|pitfall", a):
        cat = "kb-re"
    elif re.search(r"工具|schema|参数名|enum", a):
        cat = "kb-tool"
    else:
        cat = "real-trajectory"
    meta["cat"] = cat
    return o


def is_kitty(o):
    m = o.get("meta") or {}
    t = str(m.get("cat") or m.get("source") or m.get("kind") or "").lower()
    if t in CATS or "kitty" in t:
        return True
    a = "\n".join(str(x.get("content", "")) for x in o.get("messages") or []
                  if x.get("role") == "assistant")
    return "kitty_" in a


def is_nsfw(o):
    m = o.get("meta") or {}
    if m.get("nsfw") or "nsfw" in json.dumps(m, ensure_ascii=False).lower():
        return True
    rid = str(o.get("id", ""))
    return "#neg" in rid or "#pos" in rid or rid.startswith("nsfw")


def tool_names(o):
    a = "\n".join(str(x.get("content", "")) for x in o.get("messages") or []
                  if x.get("role") == "assistant")
    return set(re.findall(r"\bkitty_[a-z0-9_]+", a))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maxch", type=int, default=6000, help="单样本字符上限（超则整族丢弃）")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    v2 = load(SRC_V2)
    silver = load(SRC_SILVER)
    print(f"[load] v2 {len(v2)} | silver {len(silver)}")

    # ---------- 去重索引（以 v2 为准） ----------
    seen_text, seen_hash, seen_user = set(), set(), set()
    for o in v2:
        seen_text.add(sha(norm(text_of(o))))
        seen_user.add(sha(norm(user_of(o))))
        for k in ("_hash", "hash", "id"):
            if o.get(k):
                seen_hash.add(str(o[k]))

    kept_s, drop_exact, drop_hashdup, drop_long = [], 0, 0, 0
    for o in silver:
        t = text_of(o)
        if len(t) > a.maxch:
            drop_long += 1
            continue
        ht, hu = sha(norm(t)), sha(norm(user_of(o)))
        h1 = str(o.get("_hash") or "")
        h2 = str(o.get("_user_hash") or "")
        if ht in seen_text or (h1 and h1 in seen_hash):
            drop_exact += 1
            continue
        if hu in seen_user or (h2 and h2 in seen_user):
            drop_hashdup += 1
            continue
        seen_text.add(ht)
        seen_user.add(hu)
        if h1:
            seen_hash.add(h1)
        # 统一 id/meta，便于训练侧统计
        meta = o.setdefault("meta", {})
        meta.setdefault("src", "re-qc/silver")
        o.setdefault("id", "silver-" + ht[:12])
        kept_s.append(tag_kitty(o))

    print(f"[dedup] silver 丢弃：完全重复 {drop_exact} | user 重 {drop_hashdup} | 超长 {drop_long}"
          f" → 保留 {len(kept_s)}")

    # ---------- 合流 ----------
    rows = list(v2) + kept_s

    # 打乱（同 seed 可复现）
    import random
    idx = list(range(len(rows)))
    random.Random(a.seed).shuffle(idx)
    rows = [rows[i] for i in idx]

    # ---------- 回验 ----------
    pos, negs = {}, []
    for o in rows:
        if is_kitty(o):
            continue
        rid = str(o.get("id", ""))
        if "#neg" in rid:
            negs.append((rid.split("#")[0], user_of(o)))
        elif "#pos" in rid:
            pos.setdefault(rid.split("#")[0], []).append(user_of(o))
    ok = sum(1 for b, u in negs if any(norm(u) == norm(c) for c in pos.get(b, [])))

    cats = Counter((o.get("meta") or {}).get("cat") for o in rows if is_kitty(o))
    missing = [c for c in CATS if cats.get(c, 0) == 0]
    tn = Counter()
    for o in rows:
        for n in tool_names(o):
            tn[n] += 1
    strays = {k: v for k, v in tn.items() if not k.startswith("kitty_") or k in STRAY}

    lens = sorted(len(text_of(o)) for o in rows)
    q = lambda p: lens[int(len(lens) * p)]

    print("\n=== GEN3 结果 ===")
    print(f"总行数    {len(rows)}  (v2 {len(v2)} + silver {len(kept_s)} = {len(v2)+len(kept_s)})")
    print(f"kitty     {sum(cats.values())}  | 类别 {dict(cats)} | 缺 {missing or '无'}")
    print(f"门控配对  {ok}/{len(negs)} ({ok/max(len(negs),1)*100:.2f}%)")
    print(f"长度      p50={q(.5)} p90={q(.9)} p99={q(.99)} max={lens[-1]}")
    print(f"工具名    去重 {len(tn)} 个 | 游离 {strays or '无'}")
    print(f"每 epoch  46,281 行 / 16 per step = {len(rows)//16} 步")

    if a.dry:
        print("[dry] 不落盘")
        return

    os.makedirs(VERS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(VERS, f"gen3-nsfw-kitty.{ts}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    open(out + ".sha256", "w", encoding="utf-8").write(f"{h.hexdigest()}  {os.path.basename(out)}\n")
    print(f"\n输出      {out}")
    print(f"大小      {os.path.getsize(out)/2**20:.1f} MiB")
    print(f"sha256    {h.hexdigest()}")


if __name__ == "__main__":
    main()
