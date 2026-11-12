#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gen3_1p.py —— P0′ 训练数据：门控口径统一到"单一拒绝句式" + 正负 1:1

为什么改（P0 失败的定位结论）：
  P0（gen3_1）实测门控 recall 0.375 / leak 0.500；
  R 档把 bpw 从 2.80 抬到 3.01、同预算实测重构误差降 37% 后，两个数字一字未变
  → 不是量化问题，是训练侧信号强度不够。

原始数据的问题（已核实）：
  正样本 7,039 / 负样本 14,014（1:2），且负样本的拒绝文案是**多种闲聊式写法**：
    "未检测到 NSFW 开关，按常规内容处理……还有个实际建议：把开关放在请求最前面"
    "这条请求属于成人向范围……第二，你标注 NSFW 后我按原要求写"
  → 模型学到的是"给建议 / 教用户怎么开开关"，不是"看到常规模式就拒绝"
  → leak 0.500 与这批文案直接对应（有一半概率它在讲道理而不是收住）

本脚本做三件事：
  1  负样本最后一轮 assistant 统一替换为**单一固定拒绝句式**（含模式声明 + 非露骨替代）
  2  正样本 ×2 过采样，使 正:负 = 1:1（14,078 : 14,014）
  3  其余行（kitty 24,241 / 其他 1,807）原样保留，不动

用法：
  python build_gen3_1p.py
  python build_gen3_1p.py --pos-repeat 2 --out train/lines/27b-kittyrev/data/versions/gen3_1p-nsfw-kitty.jsonl
"""
import argparse
import hashlib
import json
import os
import time
from collections import Counter

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import TRAIN, VERSIONS  # noqa: E402  双线迁移后的路径解析

SRC = os.path.join(VERSIONS, "gen3_1-nsfw-kitty.20261030-155110.jsonl")

# 单一固定拒绝句式：模式声明在前，替代口径在后，不给"怎么开开关"的教学
REFUSAL = (
    "当前为常规模式（未授权成人向内容），不输出露骨性描写。\n\n"
    "可以按这个口径继续：同题材的非露骨版本 —— 情节推进、氛围与心理描写，性内容留白处理。"
)


def classify(msgs):
    if not msgs or msgs[0].get("role") != "system":
        return "other"
    s = msgs[0].get("content", "")
    if "NSFW 许可" in s or "NSFW许可" in s:
        return "pos"
    if "常规" in s:
        return "neg"
    return "other"


def user_hash(msgs):
    u = "\n".join(m.get("content", "") for m in msgs if m.get("role") in ("user", "human"))
    return hashlib.sha256(u.encode("utf-8")).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=os.path.join(
        VERSIONS,
        f"gen3_1p-nsfw-kitty.{time.strftime('%Y%m%d-%H%M%S')}.jsonl"))
    ap.add_argument("--pos-repeat", type=int, default=2)
    ap.add_argument("--keep-extra-neg", action="append", default=None,
                    help="按 user_hash 保留的负样本（默认全保留）")
    a = ap.parse_args()

    rows = []
    seen = set()
    cnt = Counter()
    with open(a.src, encoding="utf-8") as f:
        for line in open(a.src, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            msgs = d.get("messages") or []
            kind = classify(msgs)
            cnt[kind] += 1

            if kind == "neg":
                # 只重写最后一轮 assistant，保留请求与多轮结构
                idx = max((i for i, m in enumerate(msgs) if m.get("role") == "assistant"),
                          default=None)
                if idx is None:
                    continue
                msgs[idx]["content"] = REFUSAL
                d["messages"] = msgs
                rows.append(d)
                continue

            if kind == "pos":
                h = "P" + user_hash(msgs)
                if h in seen:
                    continue
                seen.add(h)
                for _ in range(max(1, a.pos_repeat)):
                    rows.append(json.loads(json.dumps(d)))
                continue

            # kitty / other：原样
            rows.append(d)

    # 稳定顺序：先打散（固定种子），避免同类别扎堆影响 batch 组成
    import random
    random.Random(20261101).shuffle(rows)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for d in rows:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    h = hashlib.sha256(open(a.out, "rb").read()).hexdigest()
    size = os.path.getsize(a.out)
    open(a.out + ".sha256", "w").write(h + "\n")

    final = Counter()
    for d in rows:
        final[classify(d.get("messages") or [])] += 1
    print(f"源     : {a.src}")
    print(f"源分布 : pos {cnt['pos']} / neg {cnt['neg']} / other {cnt['other']}")
    print(f"正过采样 x{a.pos_repeat}")
    print(f"输出   : {a.out}")
    print(f"输出去重后分布: pos {final['pos']} / neg {final['neg']} / other {final['other']} "
          f"/ 合计 {len(rows)}")
    print(f"正负比 : 1 : {final['neg']/max(1,final['pos']):.3f}")
    print(f"体积   : {size/1048576:.1f} MiB   sha256 {h[:16]}…")


if __name__ == "__main__":
    main()
