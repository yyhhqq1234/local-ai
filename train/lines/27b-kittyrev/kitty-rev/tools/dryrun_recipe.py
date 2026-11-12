#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""dryrun_recipe.py —— 零权重 dry-run：验证 qwen3_8_27b_imatrix recipe 认不认我们的张量命名

不需要 55.6 GB 权重，只要 config.json + model.safetensors.index.json。
判据：
  1) build_qwen3_5 能否从 index 构造参数视图（不读权重数据）
  2) qwen3_8_27b_imatrix 跑 recipe.assign 时是否报 "unknown parameter"
  3) assignment 覆盖率：被 assign 的张量数 / 总张量数
"""
import sys
from pathlib import Path

NINFER = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\tmp\_v4assets\_ninfer\ninfer-all-master"
MERGED = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\tmp\_dryrun\merged"
IMATRIX = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\tmp\_v4assets\meta\imatrix-v4.dat"

sys.path.insert(0, NINFER)


def main():
    print("=== 1. import ===")
    try:
        from tools.convert.qwen3_5 import build_model
        from tools.convert.official_recipes import RECIPES
        from tools.convert.recipe import Recipe
        print("  imports OK")
    except Exception as e:
        print(f"  IMPORT FAIL: {type(e).__name__}: {e}")
        return 2

    print("=== 2. build_model (no weights, index-only) ===")
    try:
        from tools.convert.sources.safetensors import SafetensorsSource
        base = SafetensorsSource(Path(MERGED))
        print(f"  SafetensorsSource OK: config keys={len(base.config)}")
        model = build_model(base, components=("text", "mtp"))
    except Exception as e:
        print(f"  BUILD FAIL: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 3

    params = getattr(model, "parameters", None)
    print(f"  model class = {type(model).__name__}")
    print(f"  parameters  = {len(params) if params is not None else 'N/A'}")
    if params:
        proj = [n for n, p in params.items() if getattr(p, "projection", False)]
        print(f"  projection params = {len(proj)}")
        print("  sample:", list(params)[:5])

    print("=== 3. recipe: qwen3_8_27b_imatrix ===")
    if "qwen3_8_27b_imatrix" not in RECIPES:
        print("  RECIPE MISSING; available:", list(RECIPES))
        return 4
    try:
        recipe = Recipe(model)
        class Src:
            def __init__(self, p): self.path = Path(p)
        sources = {"imatrix": Src(IMATRIX), "base": Src(MERGED)}
        RECIPES["qwen3_8_27b_imatrix"](model, recipe, sources)
        print("  recipe ran OK")
    except Exception as e:
        print(f"  RECIPE FAIL: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return 5

    print("=== 4. coverage ===")
    try:
        from collections import Counter
        sel = getattr(recipe, "selections", None)
        pol = getattr(recipe, "policies", None)
        print(f"  selections type={type(sel).__name__} n={len(sel) if hasattr(sel, '__len__') else 'NA'}")
        print(f"  policies   type={type(pol).__name__} n={len(pol) if hasattr(pol, '__len__') else 'NA'}")
        names = set()
        fmts = Counter()
        if isinstance(sel, dict):
            for k, v in sel.items():
                names.add(k)
                f = v.get("format") if isinstance(v, dict) else getattr(v, "format", None)
                fmts[str(f)] += 1
        elif hasattr(sel, "__iter__"):
            for item in sel:
                names.add(item)
        print(f"  distinct targets = {len(names)}")
        if fmts:
            print("  format distribution:")
            for f, c in fmts.most_common():
                print(f"    {f:<24} {c}")
        params = getattr(model, "parameters", {}) or {}
        missing = [n for n in params if n not in names]
        print(f"  params={len(params)} covered={len(names & set(params))} missing={len(missing)}")
        for m in missing[:8]:
            print("    -", m)
    except Exception as e:
        print(f"  COVERAGE CHECK FAIL: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
