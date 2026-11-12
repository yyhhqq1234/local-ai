#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""compact_tt.py —— 把逐张量 --tensor-type 表压成按层类正则，绕开 Windows 命令行 32K 上限

背景：gsq_rco_plan.py 输出 866 行（41 KB），subprocess 拉起 llama-quantize 直接
      FileNotFoundError [WinError 206]（CreateProcess 命令行 32767 字符上限）。

做法：把 `^blk\.<N>\.<tensor>$=TYPE` 归并成 `^blk\.\d+\.<tensor>$=TYPE`，
      但只在"同一层类全部取同一类型"时才归并；有分歧的保留逐条。

验收（强制）：
  1) 用 gguf 里的真实张量名，把 compact 表展开成逐张量映射，
     必须与原始 plan 表 **逐项相等**（多一条/少一条/类型不同 → 非 0 退出）
  2) 报告压缩后字符数与行数

用法：
  python compact_tt.py --gguf <bf16.gguf> --plan <types.txt> --out <compact.txt>
"""
import argparse
import os
import re
import sys
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.dirname(HERE)


def read_tensor_names(path):
    import gguf
    r = gguf.GGUFReader(path)
    return [t.name for t in r.tensors]


def read_plan(path):
    m = {}
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("--tensor-type "):
            line = line[len("--tensor-type "):].strip()
        k, v = line.rsplit("=", 1)
        k = k.strip()
        if not (k.startswith("^") and k.endswith("$")):
            raise SystemExit(f"[FATAL] 非锚定行，拒绝处理: {line}")
        m[k[1:-1].replace("\\.", ".")] = v.strip()
    return m


def generalize(name):
    """blk.12.attn_norm.weight -> ^blk\\.\\d+\\.attn_norm\\.weight$"""
    m = re.match(r"^blk\.(\d+)\.(.+)$", name)
    if m:
        return "^blk\\.\\d+\\." + re.escape(m.group(2)) + "$"
    return "^" + re.escape(name) + "$"


def apply_map(names, mapping):
    """按 name->type 精确表展开"""
    out = {}
    for n in names:
        if n in mapping:
            out[n] = mapping[n]
    return out


def apply_regex(names, patterns):
    """按 正则->type 表展开（后出现的覆盖先出现的，模拟 llama-quantize 逐条覆盖）"""
    out = {}
    comp = [(re.compile(p), t) for p, t in patterns]
    for n in names:
        hit = None
        for rx, t in comp:
            if rx.search(n):
                hit = t
        if hit:
            out[n] = hit
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    sys.path.insert(0, os.path.join(TRAIN, "tools", "lc", "gguf-py"))
    names = read_tensor_names(a.gguf)
    plan = read_plan(a.plan)
    print(f"[in] 张量 {len(names)} | plan 条目 {len(plan)}")

    exact = apply_map(names, plan)
    miss = [n for n in names if n not in plan]
    if miss:
        raise SystemExit(f"[FATAL] plan 未覆盖 {len(miss)} 个张量，例: {miss[:3]}")

    # 归并：同一 layer-class 且类型一致的合一条
    groups = {}
    for n, t in exact.items():
        g = generalize(n)
        groups.setdefault(g, {}).setdefault(t, []).append(n)

    compact = []
    split = 0
    for g, bytype in groups.items():
        if len(bytype) == 1:
            compact.append((g, next(iter(bytype))))
        else:
            split += 1
            for t, members in bytype.items():
                for m in members:
                    compact.append(("^" + re.escape(m) + "$", t))
    # 顺序稳定：按模式串排序，保证可复现
    compact.sort()

    back = apply_regex(names, compact)
    diff = [(n, exact[n], back.get(n)) for n in exact if back.get(n) != exact[n]]
    if diff or len(back) != len(exact):
        print(f"[FATAL] 归并后不一致 {len(diff)} 处，例: {diff[:5]}")
        return 1

    txt = "\n".join(f"{p}={t}" for p, t in compact) + "\n"
    open(a.out, "w", encoding="utf-8", newline="\n").write(txt)
    chars = len(txt)
    print(f"[out] 归并组 {len(compact)} 条（含无法归并的分裂张量，涉及 {split} 个组）")

    # 命令行上限：--tensor-type <p>=<t> 每条按 "--tensor-type " + p + "=" + t 估
    cmdlen = sum(len("--tensor-type ") + len(p) + 1 + len(t) + 1 for p, t in compact)
    cmdlen += len(a.plan) + len(a.out) + 200
    print(f"[size] 文件 {chars} 字符 | 估算命令行 {cmdlen} 字符（上限 32767）")
    if cmdlen > 32000:
        print("[WARN] 仍超限，需要更粗的归并粒度（按层带 blk.\\d+ 或 blk\\.(1?[0-9]) 分桶）")
    print(f"[verify] 逐张量等价 PASS（{len(exact)} 张量）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
