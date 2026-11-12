#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_imatrix_compat.py —— 零权重验证：我们的 imatrix 文件能不能被 qwen3_8_27b_imatrix 的
grouped_search 读进去。

背景（V5 方案 §0.5 未验证项 1）：
  · 我们的 imatrix-v4r.dat 是 **GGUF v3 容器**（magic "GGUF" / 1984 条目），
    因为 llama-imatrix 在 -o 后缀不是 .gguf 时给了一条 warn：
      "save_imatrix: saving imatrix using GGUF format with a different suffix than .gguf"
  · 而 ninfer 的 tools.convert.imatrix 可能期望 legacy .dat 格式
  ⇒ 这是 T3 convert 的最大单一风险，本脚本用「只读头部 + 试探解析」判定，不花一分钱。

判据：
  A. 文件 magic 判定（GGUF v3 / legacy dat / 未知）
  B. ninfer 侧 imatrix 读取器能否打开它
  C. recipe 的 grouped_search 需要的字段（entries / chunk count / shape 映射）是否齐
"""
import sys
from pathlib import Path

NINFER = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\tmp\_v4assets\_ninfer\ninfer-all-master"
CANDIDATES = [
    ("v4r (GGUF v3, 实际要用的)", r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\tmp\_v4assets\meta\imatrix-v4.dat"),
    ("v4 legacy (旧, 备用)", r"D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\tmp\_v4assets\meta\imatrix-v4.dat"),
]

sys.path.insert(0, NINFER)


def sniff(path):
    p = Path(path)
    if not p.exists():
        return f"MISSING {path}", None
    b = p.read_bytes()[:64]
    size = p.stat().st_size
    if b[:4] == b"GGUF":
        import struct
        ver = struct.unpack("<I", b[4:8])[0]
        nt = struct.unpack("<Q", b[8:16])[0]
        return f"GGUF v{ver}, tensor_count={nt}, size={size:,}", "gguf"
    if b[:4] == b"\x00\x00\x00\x00" or b[:2] in (b"\x00\x00",):
        return f"binary (magic 0x00000000), size={size:,}", "legacy?"
    return f"unknown magic={b[:8].hex()}, size={size:,}", "unknown"


def try_ninfer_reader(path):
    """找 ninfer 侧的 imatrix 读取实现并试打开"""
    try:
        import importlib
        mod = importlib.import_module("tools.convert.imatrix")
        print(f"  module tools.convert.imatrix 存在: {mod}")
        funcs = [a for a in dir(mod) if not a.startswith("_")]
        print(f"  公开符号: {funcs}")
        for name in ("load", "read", "open", "Imatrix", "load_imatrix"):
            obj = getattr(mod, name, None)
            if obj is None:
                continue
            print(f"  尝试 {name}({path}) ...")
            try:
                r = obj(path) if callable(obj) else None
                print(f"    OK -> {type(r).__name__} {getattr(r, 'entries', '')}")
                return True
            except Exception as e:
                print(f"    FAIL: {type(e).__name__}: {e}")
        return False
    except ImportError as e:
        print(f"  没有 tools.convert.imatrix 模块: {e}")
        return None
    except Exception as e:
        print(f"  探测异常: {type(e).__name__}: {e}")
        return None


def main():
    print("=== 1. 文件头嗅探 ===")
    kinds = {}
    for label, p in CANDIDATES:
        desc, kind = sniff(p)
        kinds[label] = kind
        print(f"  {label}\n    {p}\n    -> {desc}  (kind={kind})")

    print("\n=== 2. ninfer imatrix 读取器 ===")
    first = CANDIDATES[0][1]
    try_ninfer_reader(first)

    print("\n=== 3. recipe 里 grouped_search 怎么用 imatrix ===")
    try:
        from tools.convert import official_recipes as OR
        import inspect
        src = inspect.getsource(OR.qwen3_8_27b_imatrix)
        for line in src.splitlines():
            if "imatrix" in line or "grouped_search" in line:
                print("  " + line.strip())
    except Exception as e:
        print(f"  读取 recipe 源码失败: {type(e).__name__}: {e}")

    print("\n=== 4. 结论 ===")
    k = kinds.get(CANDIDATES[0][0])
    if k == "gguf":
        print("  我们的 imatrix 是 GGUF v3 容器。若 ninfer 侧只认 legacy .dat，")
        print("  T3 第一次 convert 会失败 → 按 V5 §5 D1 用 legacy 文件重试。")
        print("  ⇒ **开机前必须知道 legacy 版本在不在**（见下方文件清点）")
    print("  建议：把本脚本输出贴进 PR-T3 的 Q3（计划假设是否被推翻）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
