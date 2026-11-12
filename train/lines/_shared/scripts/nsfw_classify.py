#!/usr/bin/env python
"""nsfw_classify.py — NSFW 小说全量多维分类器（v2）

口径（按操作者要求）：
  · 只做分类，零剔除 —— 扫到的文件 100% 进入索引，一条不丢
  · 不改原文、不删内容、不写筛选规则
  · 每条给 8 个维度标签，任何下游可以按标签取任意子集

八个维度：
  1) topic      题材多标签（加权关键词，14 类）
  2) level      强度 L0-L3（显式词密度）
  3) form       结构形态：章节连载 / 短篇集 / 多作者合集 / 单篇
  4) pov        人称：第一人称 / 第三人称 / 混合
  5) size       篇幅档：S<5万 / M 5-20万 / L 20-100万 / XL>100万
  6) dialogue   对话密度档：高(>25%) / 中 / 低(<8%)  —— 决定适不适合改写成对话式 SFT
  7) author     作者（从文件名/正文「作者：X」提取）
  8) meta_genre 元标签：同人 / 原创 / 系统流 / 合集

输出:
  train/lines/_shared/data/nsfw-index/index.jsonl   每文件一行（全量）
  train/lines/_shared/data/nsfw-index/facets.json   每个维度的分面统计（可直接做采样权重）
  train/lines/_shared/data/nsfw-index/files.txt     相对路径清单（全量，与 index 行序对齐）

用法:
  python nsfw_classify.py --src "user-temp/NSFW小说" --out train/lines/_shared/data/nsfw-index
"""
import argparse
import hashlib
import json
import os
import re
from collections import Counter, defaultdict

# ---------- 编码 ----------
def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace"), "utf-8-sig"
    for enc in ("utf-8", "gb18030"):
        try:
            t = raw.decode(enc)
            if t.count("\ufffd") / max(len(t), 1) < 0.01:
                return t, enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8-replace"


# ---------- 维度 1：题材 ----------
TOPIC_KW = {
    "催眠":    [("催眠", 3), ("洗脑", 2), ("精神控制", 3), ("暗示", 1), ("手环", 1)],
    "调教":    [("调教", 3), ("驯服", 2), ("服从", 1), ("惩罚", 1), ("项圈", 2), ("奴隶", 2)],
    "后宫":    [("后宫", 3), ("妻妾", 2), ("众女", 2), ("收为", 1), ("美少女们", 1)],
    "近亲":    [("女儿", 2), ("母亲", 2), ("妹妹", 2), ("姐姐", 1), ("父女", 3), ("兄妹", 3), ("乱伦", 3), ("小姨子", 2)],
    "低龄向":  [("萝莉", 3), ("幼女", 3), ("正太", 3), ("小学生", 3), ("幼年", 2), ("幼齿", 3)],
    "NTR":     [("绿奴", 3), ("ntr", 3), ("黄毛", 3), ("出轨", 2), ("婚伴", 2), ("牛头人", 3)],
    "非人":    [("兽人", 3), ("兽耳", 2), ("魔族", 2), ("异种", 2), ("触手", 3), ("史莱姆", 2)],
    "同人":    [("斗罗", 3), ("原神", 3), ("崩坏", 3), ("海贼", 3), ("火影", 3), ("碧蓝", 3), ("塔菲", 2), ("明日方舟", 3), ("vtuber", 2)],
    "异世界":  [("异世界", 3), ("穿越", 2), ("转生", 2), ("系统", 1), ("大陆", 1), ("魔王", 1)],
    "虚拟游戏":[("vrmmo", 3), ("虚拟现实", 3), ("副本", 1), ("网游", 2), ("登录", 1)],
    "婚恋":    [("女友", 2), ("未婚妻", 2), ("妻子", 2), ("岳母", 2), ("婚礼", 1), ("同居", 1)],
    "百合":    [("百合", 3), ("女女", 2), ("少女之间", 2), ("姬友", 2)],
    "束缚":    [("捆绑", 2), ("鞭", 2), ("绳", 1), ("皮革", 1), ("调教", 1)],
    "露出":    [("露出", 3), ("野外", 2), ("公开", 1), ("偷窥", 1), ("公共", 1)],
}

# ---------- 维度 2：强度 ----------
EXPLICIT = ["肉棒","精液","阴道","阴茎","子宫","龟头","乳头","淫水","抽插","射精",
            "高潮","呻吟","性交","口交","肛","骚","淫","插","舔","蜜穴","肉壶"]
EXPLICIT_FP = ["乳酸","乳房癌","乳白","插入语","肛肠科"]

CHAP_RE = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千零两]+[章节回卷話话]|Chapter\s+\d+|【第?\d+[章节回】]|[（(]\s*\d+\s*[)）])", re.M)
AUTHOR_RE = re.compile(r"作者[：:]\s*([^\s\]】）)]+)")


def split_name(rel):
    base = os.path.splitext(os.path.basename(rel))[0]
    return base


def classify(path, rel):
    text, enc = read_text(path)
    n = max(len(text), 1)
    low = text.lower()

    # 1) 题材
    topics = []
    for tag, kws in TOPIC_KW.items():
        s = 0.0
        for w, wt in kws:
            c = low.count(w.lower())
            if c:
                s += wt * (1 + min(c, 20) / 20.0)
        if s >= 3:
            topics.append([tag, round(s, 1)])
    topics.sort(key=lambda x: -x[1])

    # 2) 强度
    ex = sum(low.count(w) for w in EXPLICIT) - sum(low.count(w) for w in EXPLICIT_FP)
    dens = ex / n * 1000.0
    level = "L3" if dens >= 8 else "L2" if dens >= 3 else "L1" if dens >= 0.8 else "L0"

    # 3) 形态
    chapters = len(CHAP_RE.findall(text))
    paras = len([p for p in re.split(r"\n\s*\n", text) if p.strip()])
    name = split_name(rel)
    if any(k in name for k in ("合集", "作品集", "文集")):
        form = "多篇合集"
    elif chapters >= 20:
        form = "章节连载"
    elif chapters >= 3:
        form = "多章短篇"
    else:
        form = "单篇"

    # 4) 人称
    first = low.count("我")
    third = low.count("他") + low.count("她")
    ratio = first / max(first + third, 1)
    pov = "第一人称" if ratio > 0.6 else "第三人称" if ratio < 0.35 else "混合"

    # 5) 篇幅
    wan = n / 10000.0
    size = "XL>100万" if wan >= 100 else "L20-100万" if wan >= 20 else "M5-20万" if wan >= 5 else "S<5万"

    # 6) 对话密度
    quotes = text.count("“") + text.count("「") + text.count('"')
    dr = quotes * 2 / n  # 粗略：每引号对约 2 字符标记 → 按字数比
    dialogue = "高" if dr > 0.012 else "中" if dr > 0.004 else "低"

    # 7) 作者
    m = AUTHOR_RE.search(name) or AUTHOR_RE.search(text[:5000])
    author = m.group(1) if m else ("合集内多作者" if form == "多篇合集" else "未标注")

    # 8) 元标签
    meta = []
    if any(t in dict(topics) for t in ("同人",)):
        meta.append("同人")
    else:
        meta.append("原创")
    if "系统" in low[:20000]:
        meta.append("系统流")
    if form == "多篇合集":
        meta.append("合集")

    # 去重指纹（全量保留，仅用于识别同文多版本）
    norm = re.sub(r"[\s\W_]+", "", text[:120000])
    fp = hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:16]

    return {
        "rel": rel,
        "enc": enc,
        "chars": n,
        "chapters": chapters,
        "paras": paras,
        "topic": topics,
        "level": level,
        "form": form,
        "pov": pov,
        "size": size,
        "dialogue": dialogue,
        "author": author,
        "meta_genre": meta,
        "explicit_per_kchar": round(dens, 2),
        "fp": fp,
        "kept": True,           # 全量保留标记，恒真
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    files = []
    for root, _, names in os.walk(a.src):
        for nm in sorted(names):
            if nm.lower().endswith((".txt", ".md")):
                files.append(os.path.join(root, nm))
    files.sort()
    print(f"[SCAN] {len(files)} 个文本文件 → 全量分类（不剔除）")

    os.makedirs(a.out, exist_ok=True)
    rows = []
    for p in files:
        rel = os.path.relpath(p, a.src)
        try:
            rows.append(classify(p, rel))
        except Exception as e:
            # 分类失败也保留条目，标 err，绝不丢
            rows.append({"rel": rel, "err": str(e), "kept": True, "chars": 0,
                         "topic": [], "level": "?", "form": "?", "pov": "?",
                         "size": "?", "dialogue": "?", "author": "?", "meta_genre": []})

    with open(os.path.join(a.out, "index.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(a.out, "files.txt"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r["rel"] + "\n")

    # 分面统计
    facets = defaultdict(Counter)
    for r in rows:
        for dim in ("level", "form", "pov", "size", "dialogue"):
            facets[dim][r.get(dim, "?")] += 1
        for t, _ in r.get("topic", []):
            facets["topic"][t] += 1
        for g in r.get("meta_genre", []):
            facets["meta_genre"][g] += 1
        facets["author"][r.get("author", "?")] += 1

    total_chars = sum(r.get("chars", 0) for r in rows)
    out = {
        "files": len(rows),
        "kept": sum(1 for r in rows if r.get("kept")),
        "dropped": 0,
        "total_chars": total_chars,
        "total_wan": round(total_chars / 10000, 1),
        "facets": {k: dict(v.most_common()) for k, v in facets.items()},
        "err_files": [r["rel"] for r in rows if "err" in r],
        "dup_fp_groups": len(rows) - len({r.get("fp") for r in rows if r.get("fp")}),
    }
    with open(os.path.join(a.out, "facets.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OUT] {len(rows)} 条全量索引 / {total_chars:,} 字 / 剔除 0")
    for dim in ("level", "form", "pov", "size", "dialogue"):
        print(f"  {dim:9s} {dict(facets[dim].most_common())}")


if __name__ == "__main__":
    main()
