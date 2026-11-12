#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_gen2_nsfw_kitty.py —— 第 2 代（NSFW 门控 + kitty 工作台重训）训练集构建

组成：
  A. train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated.jsonl        22180 条（pos 6999 / neg 13998 / ctl 1200）
     —— 门控成对样本，2B 硬性要求，全量保留
  B. train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-bucketed.jsonl  23718 条
     —— kitty 逆向工作台内容，全量重训（含参数格式归一 + 零样本 action 补强）
  C. 抗遗忘抽样（混合少量通用/长上下文能力，防止只训 A+B 把基础能力压掉）
     - mix-2a-bucketed.jsonl  采样 N_A（短样本，agent/常规对话）
     - mix-2c-gated-bucketed.jsonl 采样 N_C（长上下文样本）

处理：
  · 严格去重（messages 序列化 sha1 全等）
  · 去重后按 seed 42 稳定打乱
  · 快照落 data/versions/gen2-nsfw-kitty.<ts>.jsonl + .sha256
  · 打印构成统计 + 估算 token / 步数

用法：
  C:\\ProgramData\\anaconda3\\python.exe train\\scripts\\build_gen2_nsfw_kitty.py [--na 1000] [--nc 600] [--no-shuffle]
"""
import argparse
import hashlib
import json
import os
import random
import time

TRAIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(TRAIN_ROOT, "data")
VERS = os.path.join(DATA, "versions")

SRC_A = os.path.join(DATA, "nsfw-gated", "train-2b-gated.jsonl")
SRC_B = os.path.join(DATA, "kitty-reverse", "train-kitty-v3-bucketed.jsonl")
SRC_C1 = os.path.join(DATA, "mix-2a-bucketed.jsonl")
SRC_C2 = os.path.join(DATA, "mix-2c-gated-bucketed.jsonl")


def key_of(obj):
    m = obj.get("messages") or []
    blob = json.dumps(m, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def approx_tokens(obj):
    """粗估：中文字符 ≈1 token，ASCII ≈0.28 token；只用于报账，不做训练依据"""
    n = 0.0
    for msg in obj.get("messages") or []:
        c = msg.get("content") or ""
        if not isinstance(c, str):
            c = json.dumps(c, ensure_ascii=False)
        cjk = sum(1 for ch in c if "\u4e00" <= ch <= "\u9fff")
        n += cjk + (len(c) - cjk) * 0.28
    return n


def load_all(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def take_sample(path, n, seed):
    """蓄水池抽样，不整文件读入内存（mix-2c 179MB）"""
    rnd = random.Random(seed)
    res = []
    i = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            i += 1
            if len(res) < n:
                res.append(obj)
            else:
                j = rnd.randrange(i)
                if j < n:
                    res[j] = obj
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--na", type=int, default=1000, help="mix-2a 抗遗忘抽样条数")
    ap.add_argument("--nc", type=int, default=600, help="mix-2c 长上下文抽样条数")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-shuffle", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    for p in (SRC_A, SRC_B, SRC_C1, SRC_C2):
        if not os.path.exists(p):
            raise SystemExit(f"[FATAL] 缺数据源: {p}")

    print("[load] A nsfw-gated")
    A = load_all(SRC_A)
    print(f"       {len(A)} 条")
    print("[load] B kitty-v3")
    B = load_all(SRC_B)
    print(f"       {len(B)} 条")
    print(f"[load] C 抗遗忘抽样 na={a.na} nc={a.nc}")
    C = take_sample(SRC_C1, a.na, a.seed) + take_sample(SRC_C2, a.nc, a.seed + 1)
    print(f"       {len(C)} 条")

    # 去重（A 优先 → B → C）
    seen = set()
    kept = []
    stat = {"A": [0, 0], "B": [0, 0], "C": [0, 0]}
    for tag, rows in (("A", A), ("B", B), ("C", C)):
        for obj in rows:
            k = key_of(obj)
            if k in seen:
                stat[tag][1] += 1
                continue
            seen.add(k)
            stat[tag][0] += 1
            kept.append((tag, obj))

    if not a.no_shuffle:
        random.Random(a.seed).shuffle(kept)

    os.makedirs(VERS, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = a.out or os.path.join(VERS, f"gen2-nsfw-kitty.{ts}.jsonl")

    tok_total = 0.0
    by_tag_tok = {"A": 0.0, "B": 0.0, "C": 0.0}
    pos = neg = 0
    with open(out, "w", encoding="utf-8") as f:
        for tag, obj in kept:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            t = approx_tokens(obj)
            tok_total += t
            by_tag_tok[tag] += t
            mid = str(obj.get("id", ""))
            if "#neg" in mid:
                neg += 1
            elif tag == "A":
                pos += 1

    h = hashlib.sha256()
    with open(out, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with open(out + ".sha256", "w", encoding="utf-8") as f:
        f.write(f"{digest}  {os.path.basename(out)}\n")

    size = os.path.getsize(out)
    print("\n=== 构建结果 ===")
    print(f"输出      {out}")
    print(f"大小      {size/2**20:.1f} MiB   行数 {len(kept)}")
    print(f"sha256    {digest}")
    print("构成       A nsfw-gated 保留 %d / 去重 %d" % tuple(stat["A"]))
    print("           B kitty-v3   保留 %d / 去重 %d" % tuple(stat["B"]))
    print("           C 抗遗忘     保留 %d / 去重 %d" % tuple(stat["C"]))
    print(f"门控       正(id无#neg) {pos} / 负(#neg) {neg}")
    print(f"估算 token 总 {tok_total/1e6:.2f} M   A={by_tag_tok['A']/1e6:.2f}M "
          f"B={by_tag_tok['B']/1e6:.2f}M C={by_tag_tok['C']/1e6:.2f}M")
    for ctx, ga in ((2048, 16), (2048, 8), (4096, 8)):
        steps = int(tok_total / ctx / ga)
        print(f"            ctx={ctx} ga={ga} → 约 {steps} 步/epoch")
    print("\n快照已落 versions/，训练脚本用这个绝对路径：")
    print(f"  {out}")


if __name__ == "__main__":
    main()
