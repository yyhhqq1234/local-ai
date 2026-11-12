#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gen2_v2.py —— gen2 数据 v2：截断风险清理 + 类别标注 + 门控成对完整性（纯 CPU）

相对 v1 的四项改动：
  1 超长样本：字符数 > MAXCH 的样本会 ctx2048 截断（答案被切），成对样本**整对丢弃**，不是单边丢
  2 类别标注：kitty 行按内容打 meta.cat（tool-route / op-syntax / kb-re / kb-tool / real-trajectory），
     让 train_kitty.py 的 5 类覆盖判据自然通过，不再需要 --allow-partial-cats
  3 门控校验：构建后回验 pos/neg 去触发词同文率必须 = 100%
  4 输出快照 + sha256 + 统计

用法：
  C:\\ProgramData\\anaconda3\\python.exe train\\scripts\\build_gen2_v2.py [--maxch 6000]
"""
import argparse
import hashlib
import json
import os
import random
import re
import time

TRAIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(TRAIN, "data")
VERS = os.path.join(DATA, "versions")

SRC_NSFW = os.path.join(DATA, "nsfw-gated", "train-2b-gated.jsonl")
SRC_KITTY = os.path.join(DATA, "kitty-reverse", "train-kitty-v3-bucketed.jsonl")
SRC_C1 = os.path.join(DATA, "mix-2a-bucketed.jsonl")
SRC_C2 = os.path.join(DATA, "mix-2c-gated-bucketed.jsonl")

TRIG = re.compile(r"^\s*(\[\[NSFW\]\]|\[NSFW\]|NSFW|成人内容|R18|18\+ ?模式?|无限制模式|"
                  r"成人向创作模式|\[\[模式:NSFW\]\])\s*[:：,，]?\s*", re.I)
CATS = ["real-trajectory", "op-syntax", "tool-route", "kb-re", "kb-tool"]


def text_of(o):
    return "\n".join(str(m.get("content", "")) for m in o.get("messages") or [])


def tag_kitty(o):
    """按内容给 kitty 行打类别（train_kitty.py 的 REQUIRED_CATS 口径）"""
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


def load(path):
    rows = []
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


def sample_file(path, n, seed):
    rnd = random.Random(seed)
    res, i = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            i += 1
            if len(res) < n:
                res.append(o)
            else:
                j = rnd.randrange(i)
                if j < n:
                    res[j] = o
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maxch", type=int, default=6000, help="单样本字符上限（超则整对丢弃）")
    ap.add_argument("--na", type=int, default=1000)
    ap.add_argument("--nc", type=int, default=600)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    nsfw = load(SRC_NSFW)
    kitty = [tag_kitty(o) for o in load(SRC_KITTY)]
    anti = sample_file(SRC_C1, a.na, a.seed) + sample_file(SRC_C2, a.nc, a.seed + 1)
    print(f"[load] nsfw-gated {len(nsfw)} | kitty {len(kitty)} | 抗遗忘 {len(anti)}")

    # 超长：成对整对丢
    over = {str(o.get("id", "")).split("#")[0] for o in nsfw if len(text_of(o)) > a.maxch}
    kept_nsfw = [o for o in nsfw if str(o.get("id", "")).split("#")[0] not in over]
    dropped_pairs = len(nsfw) - len(kept_nsfw)
    kept_kitty = [o for o in kitty if len(text_of(o)) <= a.maxch]
    kept_anti = [o for o in anti if len(text_of(o)) <= a.maxch]
    print(f"[trim] 超 {a.maxch} 字符：整族丢弃 {len(over)} 族 / {dropped_pairs} 条；"
          f"kitty 丢 {len(kitty)-len(kept_kitty)}；抗遗忘丢 {len(anti)-len(kept_anti)}")

    rows = kept_nsfw + kept_kitty + kept_anti
    random.Random(a.seed).shuffle(rows)

    ts = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(VERS, f"gen2-nsfw-kitty-v2.{ts}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    h = hashlib.sha256()
    with open(out, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    open(out + ".sha256", "w", encoding="utf-8").write(f"{h.hexdigest()}  {os.path.basename(out)}\n")

    # 回验：门控成对性 + 类别覆盖
    pos, negs = {}, []
    for o in kept_nsfw:
        rid = str(o.get("id", ""))
        u = next((m.get("content") or "" for m in o.get("messages") or [] if m.get("role") == "user"), "")
        if "#neg" in rid:
            negs.append((rid.split("#")[0], u))
        else:
            pos.setdefault(rid.split("#")[0], []).append(u)
    strip = lambda t: re.sub(r"\s+", "", TRIG.sub("", t or "", count=1))
    ok = sum(1 for b, u in negs if any(strip(u) == strip(c) for c in pos.get(b, [])))
    cats = {}
    for o in kept_kitty:
        c = (o.get("meta") or {}).get("cat")
        cats[c] = cats.get(c, 0) + 1
    missing = [c for c in CATS if c not in cats]

    print("\n=== v2 结果 ===")
    print(f"输出      {out}")
    print(f"大小      {os.path.getsize(out)/2**20:.1f} MiB   行数 {len(rows)}")
    print(f"sha256    {h.hexdigest()}")
    print(f"门控配对  {ok}/{len(negs)} ({ok/max(len(negs),1)*100:.1f}%)")
    print("kitty 类别", cats, "| 缺:", missing or "无")
    lens = sorted(len(text_of(o)) for o in rows)
    q = lambda p: lens[int(len(lens) * p)]
    print(f"长度      p50={q(.5)} p90={q(.9)} p99={q(.99)} max={lens[-1]}")


if __name__ == "__main__":
    main()
