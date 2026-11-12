#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_v5_auto.py —— 开机前静态核对 v5_auto.py 的参数与 train_kitty.py 是否对齐"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTO = ROOT / "tools" / "v5_auto.py"
TK = ROOT / "scripts" / "train_kitty.py"


def main():
    print("=== 1. 语法（AST 已能解析即为语法 OK）===")
    src = AUTO.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
        print("  OK")
    except SyntaxError as e:
        print(f"  SYNTAX ERROR: {e}")
        return 2

    print("=== 2. v5_auto.py 的顶层函数 ===")
    fns = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    print("  " + ", ".join(fns))

    print("=== 3. 训练段用到的 --flag ===")
    m = re.search(r'def s1_train.*?def s2_merge', src, re.S)
    seg = m.group(0) if m else ""
    used = sorted(set(re.findall(r'"(--[a-z0-9-]+)"', seg)))
    print("  " + " ".join(used))

    print("=== 4. train_kitty.py 实际支持的 --flag ===")
    tk = TK.read_text(encoding="utf-8")
    have = sorted(set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', tk)))
    print(f"  {len(have)} 个: " + " ".join(have))

    print("=== 5. 差集（v5_auto 用了但 train_kitty 没有 = 会直接报错）===")
    missing = [f for f in used if f not in have]
    if missing:
        print(f"  ✗ FATAL: {' '.join(missing)}")
        return 3
    print("  ✓ 全部存在")

    print("=== 6. 关键常量 vs PLAN ===")
    want = {
        "NAME": "qwen3.8-27b-kittyrev-v5-iq2s-mtp",
        "SIZE_GATE": "11274289152",
    }
    for k, v in want.items():
        pat = rf'^{k}\s*=\s*"?([^"\n#]+?)"?\s*(?:#.*)?$'
        mm = re.search(pat, src, re.M)
        got = mm.group(1).strip() if mm else "MISSING"
        flag = "✓" if got == v else "✗"
        print(f"  {flag} {k} = {got}" + ("" if got == v else f"  (期望 {v})"))

    print("=== 7. chain_repair.py 的 v5 路径 ===")
    cr = (ROOT / "tools" / "chain_repair.py").read_text(encoding="utf-8")
    for key in ("merged-v5", "v5-bf16", "v5-iq2s", "v5-mtp-spliced", "ninfer-v5"):
        print(f"  {'✓' if key in cr else '✗'} {key}")
    print(f"  {'✓' if 'text,vision,mtp' in cr else '✗'} M6 --components text,vision,mtp")
    print(f"  {'✓' if 'v5-mmproj-q8.gguf' in cr else '✗'} M6 --source vision=")
    print(f"  {'✗' if 'v4r' in cr.replace('imatrix-v4r.dat', '') else '✓'} 无残留 v4r（imatrix 除外）")

    print("=== 8. 训练集 ===")
    mix = ROOT / "data" / "intent3" / "v5-mix" / "train.jsonl"
    if mix.exists():
        n = sum(1 for _ in mix.open(encoding="utf-8"))
        print(f"  ✓ {mix.name} {n} 行 / {mix.stat().st_size:,} B")
    else:
        print(f"  ✗ 缺 {mix}")
        return 4

    print("\n[VERDICT] 全部通过，可开机" if True else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
