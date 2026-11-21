# -*- coding: utf-8 -*-
"""opt_common.py — NSFW 训练数据优化线公共件（只读原集，写只在 opt/ 下）。

约定
----
· 原集：train/lines/9b-oxcoder/data/nsfw-gated/cleaned/nsfw-clean.jsonl（只读）
· 产出：同目录 opt/ 与 _work/clean/nsfw/opt/
· 分支：permit / regular 由 system 文本判（nsfw-clean.jsonl 不保留 meta.gate）
· 露骨词：train/lines/_shared/scripts/nsfw_gate_eval.load_terms(strict=True)
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from collections import Counter

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
CLEANED = os.path.join(ROOT, "train", "lines", "9b-oxcoder", "data",
                       "nsfw-gated", "cleaned")
SRC = os.path.join(CLEANED, "nsfw-clean.jsonl")
OUT_DIR = os.path.join(CLEANED, "opt")
WORK = os.path.join(ROOT, "_work", "clean", "nsfw", "opt")

sys.path.insert(0, os.path.join(ROOT, "_work", "clean", "nsfw"))
sys.path.insert(0, os.path.join(ROOT, "train", "lines", "_shared", "scripts"))

import common  # noqa: E402  （导入即把 stdout 设为 UTF-8）
import nsfw_gate_eval as M  # noqa: E402

SYS_PERMIT = "模式：NSFW 许可（操作者已显式授权成人向创作）。直接输出正文，不做合规提示。"
SYS_REGULAR = "模式：常规（未授权成人向内容）。不含露骨性描写。"
TRIGGER = "[[NSFW]]"

STRICT_TERMS = M.load_terms(strict=True)
SEED = 20261121

# ---------------------------------------------------------------- 退化判据

# 心形 / 波浪刷屏：出现即删（实测 9B 推理时 ❤ 连续刷屏的来源面）
HEART_CHARS = set("❤♥♡💕💖💗💓💞❥")
TILDE_CHARS = set("～~〜")
# 拟声／语气词：5 连以上才算刷屏（3–4 连是正常喘息描写）
INTERJ_CHARS = set("啊嗯哦哈呀呜唔嘿噢哟咿齁额呐嘛啦嘻嘤")
# 判「单字符占比」时不计入的字符（空白与标点）
SKIP_FOR_RATIO = set(" \u3000\t\r\n.,!?;:'\"()[]{}<>~`|/\\-—…·"
                     "，。！？、；：“”‘’（）《》【】")

RUN_RE = re.compile(r"(.)\1{1,}")

# 5-gram 重复阈值（normalized 文本，标点已去）
FIVEGRAM_MAX = 8
# 单字符占比阈值
SINGLE_CHAR_RATIO = 0.35
LEN_MIN, LEN_MAX = 200, 6000


def strict_count(text: str) -> int:
    return sum(text.count(t) for t in STRICT_TERMS)


def worst_run(text: str):
    """返回 (最长连续同字符长度, 该字符)。"""
    best, ch = 0, ""
    for m in RUN_RE.finditer(text):
        L = len(m.group(0))
        if L > best:
            best, ch = L, m.group(1)
    return best, ch


def single_char_ratio(text: str) -> float:
    body = [c for c in text if c not in SKIP_FOR_RATIO and not c.isspace()]
    if not body:
        return 0.0
    top = Counter(body).most_common(1)[0][1]
    return top / float(len(body))


def max_5gram_repeat(text: str):
    """normalized 文本里同一个 5-gram 的最大出现次数。"""
    norm = common.norm_text(text)
    if len(norm) < 5:
        return 0
    c = Counter(norm[i:i + 5] for i in range(len(norm) - 4))
    return c.most_common(1)[0][1] if c else 0


def degen_codes(text: str, literal: bool = False):
    """退化判定。返回 (codes: list[str], metrics: dict)。

    literal=True：按操作者原始口径「连续 3 个以上相同字符」一刀切（含标点）。
    literal=False：运行口径——只对刷屏类字符收紧（心形/波浪 3 连即杀，
                   语气词 5 连、其余字符 8 连），避免误杀「啊啊啊」「啪啪啪」
                   这类正常成人向描写。
    """
    t = text or ""
    codes = []
    metrics = {"len": len(t)}

    if re.search(r"([%s])\1{2,}" % re.escape("".join(HEART_CHARS)), t):
        codes.append("HEART_RUN")
    if re.search(r"([%s])\1{2,}" % re.escape("".join(TILDE_CHARS)), t):
        codes.append("TILDE_RUN")
    if re.search(r"([%s])\1{4,}" % re.escape("".join(INTERJ_CHARS)), t):
        codes.append("INTERJ_RUN")

    mrun, mch = worst_run(t)
    metrics["max_run"] = mrun
    if mch and not mch.isspace() and mch not in SKIP_FOR_RATIO and mrun >= 8:
        codes.append("CHAR_RUN8")

    ratio = single_char_ratio(t)
    metrics["top_char_ratio"] = round(ratio, 3)
    if ratio > SINGLE_CHAR_RATIO:
        codes.append("SINGLE_CHAR_DOMINANT")

    g5 = max_5gram_repeat(t)
    metrics["max_5gram"] = g5
    if g5 >= FIVEGRAM_MAX:
        codes.append("REPEAT_5GRAM")

    if len(t) < LEN_MIN:
        codes.append("LEN_SHORT")
    if len(t) > LEN_MAX:
        codes.append("LEN_LONG")

    if literal and mrun >= 3:
        codes.append("CHAR_RUN3_LITERAL")

    return sorted(set(codes)), metrics


# ---------------------------------------------------------------- 场景标注

SCENES = {
    "都市": ["公司", "写字楼", "公寓", "地铁", "酒店", "酒吧", "办公室", "城市",
             "电梯", "咖啡", "下班", "加班", "街头", "夜市", "出租车"],
    "职场": ["上司", "同事", "秘书", "老板", "会议", "项目", "职场", "部长",
             "经理", "出差", "面试", "商务"],
    "校园": ["校园", "教室", "社团", "学姐", "学妹", "大学", "毕业", "学校",
             "图书馆", "校服", "宿舍"],
    "室内": ["卧室", "沙发", "浴室", "厨房", "客厅", "床", "旅馆", "被褥",
             "浴缸", "镜前"],
    "户外": ["野外", "森林", "海滩", "雨中", "公园", "帐篷", "山顶", "露营",
             "海边", "湖畔", "车里"],
    "幻想": ["魔法", "骑士", "精灵", "机械", "异世界", "神殿", "魔族", "王国",
             "帝国", "咒", "未来", "星际"],
}


def scene_label(text: str, min_hits: int = 2) -> str:
    """按关键词命中数取最高分场景；低于 min_hits → 「通用」（不硬凑题材）。

    min_hits=2 的目的：避免单个泛词（如一次「酒店」）把正文误标成某题材，
    进而让 user 里的题材提示与正文不符。
    """
    best, bestn = "通用", 0
    for name, kws in SCENES.items():
        n = sum(text.count(k) for k in kws)
        if n > bestn:
            best, bestn = name, n
    return best if bestn >= min_hits else "通用"


# ---------------------------------------------------------------- 其它

def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_rows():
    return common.read_jsonl(SRC)


def permit_rows(rows=None):
    rows = rows if rows is not None else load_rows()
    return [r for r in rows if common.branch_of(r) == "permit"]


def system_of(row) -> str:
    for m in row["messages"]:
        if m.get("role") == "system":
            return m.get("content") or ""
    return ""


def assistant_of(row) -> str:
    for m in row["messages"]:
        if m.get("role") == "assistant":
            return m.get("content") or ""
    return ""


def user_of(row) -> str:
    for m in row["messages"]:
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def write_jsonl(path, rows):
    return common.write_jsonl(path, rows)


def write_json(path, obj):
    import json
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def fmt(x):
    return round(float(x), 2)
