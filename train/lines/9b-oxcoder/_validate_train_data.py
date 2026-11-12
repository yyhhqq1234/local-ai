#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
训练数据加载验证器 —— 真正调用 datasets.load_dataset，复现训练时的加载路径

为什么需要：train_qlora9b.py --dry-run 在 load_dataset 之前就退出了，
           **验证不到 schema 错误**。2026-11-02 的 2B v4 就是栽在这里：
           TypeError: Couldn't cast array of type struct<...> to {...}

用法：python _validate_train_data.py <data.jsonl> [...]
"""
import sys, io, json, collections, os


def check(path):
    print("=" * 70)
    print(f"[CHECK] {path}")
    if not os.path.exists(path):
        print("  ✗ 文件不存在")
        return False
    n = sum(1 for l in io.open(path, encoding="utf-8") if l.strip())
    sz = os.path.getsize(path) / 1e6
    print(f"  {n} 行 · {sz:.1f} MB")

    # 1 纯文本层面
    keys = collections.Counter()
    roles = collections.Counter()
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            keys[tuple(sorted(d.keys()))] += 1
            for m in d["messages"]:
                roles[m["role"]] += 1
    print(f"  字段组合: {dict(keys)}")
    print(f"  角色分布: {dict(roles)}")
    if len(keys) != 1:
        print("  ✗ 字段组合不唯一 —— datasets 会推断失败")
        return False

    # 2 datasets 真实加载
    try:
        from datasets import load_dataset
        ds = load_dataset("json", data_files=path, split="train")
        print(f"  ✓ load_dataset OK → {ds.num_rows} 行")
        print(f"    features: {ds.features}")
        # 取一条看结构
        r = ds[0]
        msgs = r["messages"]
        print(f"    首条消息数={len(msgs)} 末条 role={msgs[-1]['role']}")
        if ds.num_rows != n:
            print(f"  ⚠ 行数不一致：文本 {n} vs datasets {ds.num_rows}")
        return True
    except Exception as e:
        print(f"  ✗ load_dataset 失败：{type(e).__name__}: {str(e)[:300]}")
        return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ok = True
    for p in sys.argv[1:]:
        ok = check(p) and ok
    print("=" * 70)
    print("总结论：", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
