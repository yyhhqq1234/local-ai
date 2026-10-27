#!/usr/bin/env python
"""nsfw_triage.py — NSFW 小说素材勘察与分类（数据准备第一步）

做什么：
  1) 递归扫描源目录全部 .txt，做编码探测（UTF-8 / GB18030 / UTF-16）
  2) 统计字符数、章节数、段落数
  3) 题材标签：按加权关键词表打多标签（不追求完美，只求可分层采样）
  4) 强度分级：显式词密度 → L3 明写 / L2 含露骨段 / L1 暗示 / L0 无
  5) 重复检测：正文归一化后 sha1 前 16 位（同一部作品多版本/合集重复）
  6) 输出 triage.jsonl（每文件一行）+ summary.json（汇总）

不做：不改源文件、不生成新文本、不落任何正文到输出（只落统计与标签）

用法:
  python nsfw_triage.py --src "user-temp/NSFW小说" --out train/data/nsfw-triage
"""
import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter

# ---------- 编码探测 ----------
def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", "replace"), "utf-8-sig"
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            t = raw.decode(enc)
            # GB18030 对 UTF-8 文本也能"成功"解码出乱码，用替换字符率兜底
            bad = t.count("\ufffd")
            if enc == "utf-8" or bad / max(len(t), 1) > 0.001:
                if bad / max(len(t), 1) < 0.01:
                    return t, enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8-replace"


# ---------- 题材标签（加权关键词，命中即计分） ----------
# key: 标签, val: [(词, 权重)]
TAGS = {
    "催眠":     [("催眠", 3), ("洗脑", 2), ("精神控制", 3), ("暗示", 1), ("眼镜", 1)],
    "调教":     [("调教", 3), ("驯服", 2), ("服从", 1), ("惩罚", 1), ("项圈", 2)],
    "后宫":     [("后宫", 3), ("妻妾", 2), ("多位", 1), ("众女", 2), ("收为", 1)],
    "乱伦":     [("女儿", 2), ("母亲", 2), ("妹妹", 2), ("姐姐", 1), ("家族", 1), ("父女", 3), ("兄妹", 3)],
    "幼齿":     [("萝莉", 3), ("幼女", 3), ("正太", 3), ("小学生", 3), ("幼年", 2)],
    "NTR":      [("绿奴", 3), ("ntr", 3), ("黄毛", 3), ("出轨", 2), ("婚伴", 2), ("去黑", 1)],
    "兽人":     [("兽人", 3), ("兽耳", 2), ("魔族", 2), ("异种", 2), ("触手", 3)],
    "同人":     [("斗罗", 3), ("原神", 3), ("崩坏", 3), ("海贼", 3), ("火影", 3), ("碧蓝", 3), ("塔菲", 2), ("女帝", 1)],
    "异世界":   [("异世界", 3), ("穿越", 2), ("转生", 2), ("系统", 1), ("大陆", 1)],
    "VR/游戏":  [("vrmmo", 3), ("游戏", 1), ("虚拟现实", 3), ("副本", 1)],
    "婚恋":     [("女友", 2), ("未婚妻", 2), ("妻子", 2), ("拜年", 1), ("岳母", 2)],
    "女同":     [("百合", 3), ("女女", 2), ("姬", 1)],
    "SM":       [("捆绑", 2), ("鞭", 2), ("调教", 1), ("绳", 1), ("皮革", 1)],
    "露出":     [("露出", 3), ("公开", 1), ("野外", 2), ("偷窥", 1)],
}

# 强度分级用的显式词（只用于统计密度，不做内容输出）
EXPLICIT = [
    "肉棒", "精液", "阴道", "阴茎", "子宫", "龟头", "乳头", "淫水", "抽插", "射精",
    "高潮", "呻吟", "性交", "口交", "肛", "乳", "骚", "淫", "插", "舔",
]
# 排除 FP：常见非性语境
EXPLICIT_FP = ["乳酸", "乳房癌", "乳白", "插入语"]

CHAPTER_RE = re.compile(r"^\s*(第[0-9一二三四五六七八九十百千零两]+[章节回卷話话]|Chapter\s+\d+|【第?\d+[章节回】])", re.M)


def analyze(path):
    text, enc = read_text(path)
    n = len(text)
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chapters = len(CHAPTER_RE.findall(text))
    low = text.lower()

    tag_scores = {}
    for tag, kws in TAGS.items():
        s = 0
        for w, wt in kws:
            c = low.count(w.lower())
            if c:
                s += wt * (1 + min(c, 20) / 20.0)  # 出现次数边际递减
        if s >= 3:
            tag_scores[tag] = round(s, 2)

    ex = 0
    for w in EXPLICIT:
        ex += low.count(w)
    for w in EXPLICIT_FP:
        ex -= low.count(w)
    density = ex / max(n, 1) * 1000.0  # 每千字命中数
    if density >= 8:
        level = "L3"
    elif density >= 3:
        level = "L2"
    elif density >= 0.8:
        level = "L1"
    else:
        level = "L0"

    # 去重键：去空白 + 去标点后的正文指纹
    norm = re.sub(r"[\s\W_]+", "", text[:200000])
    fp = hashlib.sha1(norm.encode("utf-8", "replace")).hexdigest()[:16]

    return {
        "path": path,
        "enc": enc,
        "chars": n,
        "paras": len(paras),
        "chapters": chapters,
        "tags": sorted(tag_scores.items(), key=lambda x: -x[1]),
        "explicit_per_kchar": round(density, 2),
        "level": level,
        "fp": fp,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    files = []
    for root, _, names in os.walk(a.src):
        for nm in names:
            if nm.lower().endswith((".txt", ".md")):
                files.append(os.path.join(root, nm))
    files.sort()
    print(f"[SCAN] {len(files)} 个文本文件")

    os.makedirs(a.out, exist_ok=True)
    rows, fps, dup = [], {}, []
    for i, p in enumerate(files, 1):
        try:
            r = analyze(p)
        except Exception as e:
            print(f"  [ERR] {p}: {e}")
            continue
        r["rel"] = os.path.relpath(p, a.src)
        if r["fp"] in fps:
            dup.append({"rel": r["rel"], "same_as": fps[r["fp"]]})
            r["dup_of"] = fps[r["fp"]]
        else:
            fps[r["fp"]] = r["rel"]
        rows.append(r)
        if i % 10 == 0:
            print(f"  {i}/{len(files)} …")

    with open(os.path.join(a.out, "triage.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_chars = sum(r["chars"] for r in rows)
    tag_counter = Counter()
    for r in rows:
        for t, _ in r["tags"]:
            tag_counter[t] += 1
    lvl = Counter(r["level"] for r in rows)
    summary = {
        "files": len(rows),
        "total_chars": total_chars,
        "total_mb": round(total_chars * 3 / 1024 / 1024, 1),  # UTF-8 中文约 3 字节
        "dup_files": len(dup),
        "level_dist": dict(lvl),
        "tag_dist": tag_counter.most_common(),
        "top10_by_chars": [
            {"rel": r["rel"], "chars": r["chars"], "level": r["level"],
             "tags": [t for t, _ in r["tags"][:3]]}
            for r in sorted(rows, key=lambda x: -x["chars"])[:10]
        ],
        "dups": dup,
    }
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n[OUT] {a.out}/triage.jsonl  {len(rows)} 行")
    print(f"      总字符 {total_chars:,}  重复 {len(dup)}")
    print(f"      强度分布 {dict(lvl)}")
    print(f"      题材 TOP: {tag_counter.most_common(10)}")


if __name__ == "__main__":
    main()
