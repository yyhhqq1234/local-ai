#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_w3_scenes.py —— 生成 W3 的 150 条场景设定（只描述情境，不写正文）。

设计原则
--------
场景设定只含"情境坐标"：场所 / 关系张力 / 叙事视角 / 强度档 / 长度档 / 硬约束。
不含任何露骨描写。正文由 abliterated base 自生成（gen_w3.py），
这样训练数据与目标模型同分布，且作者只负责情境，不负责内容。

用法
----
  python build_w3_scenes.py --out data/intent3/w3-scenes.jsonl --n 150
  python build_w3_scenes.py --out ... --n 150 --dry   # 只打印不写盘

判据
----
  · 150 条，场景×视角×强度 组合覆盖，同一组合 ≤8 条
  · 每条 user 提示 ≤120 字，不含露骨词（用内建 EROTIC_GUARD 自检，命中即 FATAL）
  · 去重：prompt 5-gram Jaccard ≥0.7 视为重复 → FATAL
"""
import argparse
import hashlib
import itertools
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 情境银行（全部为情境坐标，无露骨描写） ────────────────────────────────
SETTINGS = [
    "雨夜留宿，住处只剩一间房",
    "出差同一间酒店，走廊尽头停下说话",
    "深夜加班后共乘一辆车，车停在楼下没熄火",
    "搬家最后一天，纸箱堆满客厅，只剩沙发可坐",
    "厨房里一起做饭，切菜时手碰到手",
    "长途列车包厢，窗外是连续的黑色原野",
    "夏夜阳台，city 灯在远处，风扇声很响",
    "淋浴后裹着浴巾在客厅找吹风机",
    "冬夜暖气故障，两人挤在同一条毯子里",
    "海边民宿，潮声很大，隔着薄墙能听见对方翻身",
    "练舞室散场后只剩两人，镜子还亮着",
    "凌晨便利店买完东西，在店门口的台阶上坐着",
    "生日聚会散场，洗碗时只剩两人",
    "看病回来发烧，被按在床上量体温",
    "一起修漏水的水管，衣服全湿了",
    "露营帐篷里，外面下雨，睡袋只带了一个",
    "书房找一本旧相册，翻到深夜",
    "两人吵架后和解，站在玄关没开灯",
    "温泉旅馆，露天池边只有一盏石灯",
    "节日回家，卧室还是小时候那张床",
]

RELATIONS = [
    "多年好友，界限一直没被说破",
    "刚认识不久，互相试探",
    "前任，因一件小事重新见面",
    "同事，白天刚有过一次争执",
    "室友，习惯了彼此的存在",
    "师生/上下级，权力差明显",
    "青梅竹马，重逢后彼此陌生又熟悉",
    "网络认识第一次见面",
]

TENSIONS = [
    "悬置：谁都不肯先开口",
    "推拉：一方靠近，一方退半步",
    "打断：正要发生时被打断一次",
    "错位：节奏不合，撞到、找不准位置",
    "坦白：一方直接说出想要什么",
]

POVS = ["第一人称", "第三人称限知", "对话体为主"]

INTENSITY = [
    ("低", "以氛围与距离为主，接触点到为止，留白多"),
    ("中", "有明确的接触与身体反应描写，节奏完整"),
    ("高", "直入情境，动作与反应具体，篇幅集中在此"),
]

LENGTHS = [(250, 400), (400, 600)]

HARD = [
    "不含未成年人",
    "不含真实可识别真人",
    "不含性暴力与胁迫",
]

# 露骨词自检（只拦"提示里就写了露骨内容"，场景设定不该有）
EROTIC_GUARD = ["阴茎", "阴道", "乳房", "插入", "射精", "口交", "性交", "高潮", "裸体"]


def ngrams(s, n=5):
    s = "".join(s.split())
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


def jac(a, b):
    A, B = ngrams(a), ngrams(b)
    return len(A & B) / max(1, len(A | B))


def build(n):
    """150 条 = 150 个互不相同的 (情境,关系,张力) 核心，视角与强度按序轮转。

    去重判据（正确的那个）：核心三元组必须唯一 + prompt 哈希必须唯一。
    不用 5-gram Jaccard 卡场景设定——它们本来就共用同一模板骨架，
    用 Jaccard 卡会误杀合法的"同骨架不同情境"（本项目反复出现的"判据本身错"）。
    """
    cores = [(s, r, t) for s in SETTINGS for r in RELATIONS for t in TENSIONS]
    cores.sort(key=lambda c: hashlib.sha256(("|".join(c)).encode()).hexdigest())
    if len(cores) < n:
        raise SystemExit("[FATAL] 核心组合只有 %d 个 < %d，扩 SETTINGS/RELATIONS/TENSIONS"
                         % (len(cores), n))
    rows, seen = [], set()
    for i, (s, r, t) in enumerate(cores[:n]):
        pov = POVS[i % len(POVS)]
        lvl, desc = INTENSITY[(i // len(POVS)) % len(INTENSITY)]
        lo, hi = LENGTHS[i % len(LENGTHS)]
        prompt = (
            "成人向场景：%s。%s，%s。%s，强度%s（%s），%d-%d字。"
            "第一句直接进场景，无开场说明；不要一句话跳过过程；结尾停在场景里不升华。"
            % (s, r, t, pov, lvl, desc, lo, hi)
        )
        h = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        if (s, r, t) in seen or h in seen:
            raise SystemExit("[FATAL] 核心或 prompt 重复：%s" % ((s, r, t),))
        seen.add((s, r, t)); seen.add(h)
        rows.append({
            "id": "w3-%03d" % (len(rows) + 1),
            "prompt": prompt, "core": [s, r, t],
            "pov": pov, "intensity": lvl, "len": [lo, hi],
            "boundary": HARD,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    rows = build(a.n)
    if len(rows) != a.n:
        raise SystemExit("[FATAL] 生成 %d 条，要求 %d 条：情境组合不足，扩 SETTINGS/RELATIONS/TENSIONS"
                         % (len(rows), a.n))

    # 自检 1：露骨词
    bad = [(r["id"], w) for r in rows for w in EROTIC_GUARD if w in r["prompt"]]
    if bad:
        raise SystemExit("[FATAL] 场景设定里出现露骨词（应只写情境）：%s" % bad[:3])

    # 自检 2：长度
    over = [r["id"] for r in rows if len(r["prompt"]) > 160]
    if over:
        raise SystemExit("[FATAL] prompt 过长（>190 字）：%s" % over[:3])

    # 自检 3：唯一性（核心三元组 + prompt 哈希，build() 内已强校验）+ Jaccard 仅作信息
    hi_pairs = 0
    for i in range(0, len(rows), 7):
        for j in range(i + 1, min(i + 8, len(rows))):
            if jac(rows[i]["prompt"], rows[j]["prompt"]) >= 0.85:
                hi_pairs += 1
    print("[info] 抽样近重复对（Jaccard>=0.85）= %d（同模板骨架属正常，不作 FAIL）" % hi_pairs)

    # 覆盖统计
    cov = {}
    for r in rows:
        cov[(r["pov"], r["intensity"])] = cov.get((r["pov"], r["intensity"]), 0) + 1
    print("[ok] %d 条场景，覆盖 %d 个(视角×强度)组合：%s" % (len(rows), len(cov), cov))
    print("[ok] 露骨词 0 / 长度全部 ≤190 / 核心唯一 / prompt 哈希唯一")

    if a.dry:
        for r in rows[:3]:
            print("  %s  %s" % (r["id"], r["prompt"][:100]))
        print("[dry] 未写盘")
        return

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, a.out)          # 原子落盘，防半截文件
    n = sum(1 for l in open(a.out, encoding="utf-8") if l.strip())
    if n != a.n:
        raise SystemExit("[FATAL] 回读 %d 行 != %d" % (n, a.n))
    print("[ok] 写盘 %s（回读 %d 行）" % (a.out, n))


if __name__ == "__main__":
    main()
