#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t30_train_cache_base_fp.py -- 训练侧必须校验 act-cache 与 base 的指纹（消费侧兜底）。

缺陷现象
    `precompute_activations` 侧已有 model_fp + resume 比对（t28 覆盖）。但那只管
    **同一个 out 目录的 resume**。新目录是零检查的：
        cp -r act-cache act-cache-v4          # 或干脆忘了重建
        train_partial_lora.py --act-cache act-cache-v4 --layer-dir merged-v4
    缓存是 v3 的第 48 层 hidden，labels 是 v4 的 —— 形状一致（同架构），
    不报错、loss 正常下降、导出也能跑，但 adapter 学的是错误激活上的映射。

正确的断言
    ① 缓存指纹 ≠ 期望 → SystemExit，消息里给两边的 fp 与「前 3 项」差异
    ② 指纹一致 → 正常通过，打印「一致」
    ③ --allow-cache-base-mismatch → 放行但打印 WARNING（不是静默）
    ④ 静态断言：argparse 有 --expect-base-fp / --allow-cache-base-mismatch，
       且三处 MultiCache（train/val/refusal）都调了守卫
如果这条 FAIL 说明什么
    消费侧守卫被删/没接上 —— 混用旧缓存重新变成静默错。
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import types

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                            # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(KITTY, "scripts", "train_partial_lora.py")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load_mod(path, name):
    """train_partial_lora 顶层 import torch / F；这里只给第三方库打桩，
    被测行为（指纹比较与 FATAL 分支）与 torch 无关。"""
    if "torch" not in sys.modules:
        class _Any:
            """任何属性/调用都返回自身，可作上下文管理器 —— 只用于让 import 期装饰器不炸。"""

            def __call__(self, *a, **k):
                return _Any()

            def __getattr__(self, n):
                return _Any()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def __iter__(self):
                return iter(())

        t = types.ModuleType("torch")
        nn = types.ModuleType("torch.nn")
        fn = types.ModuleType("torch.nn.functional")
        cuda = types.ModuleType("torch.cuda")
        t.__getattr__ = lambda n: _Any()          # torch.no_grad / torch.float32 …
        nn.__getattr__ = lambda n: _Any()
        fn.__getattr__ = lambda n: _Any()
        cuda.__getattr__ = lambda n: _Any()
        t.nn, t.cuda, t.bfloat16 = nn, cuda, "bfloat16"
        nn.functional = fn
        t.Tensor = _Any
        sys.modules["torch"] = t
        sys.modules["torch.nn"] = nn
        sys.modules["torch.nn.functional"] = fn
        sys.modules["torch.cuda"] = cuda
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    M = load_mod(SRC, "tpl_t30")
    check("train_partial_lora 可 import（torch 打桩）", True)
except Exception as e:                                       # noqa: BLE001
    print(f"\nFAIL: 载入失败（{type(e).__name__}: {e}）")
    sys.exit(1)

check("① 有 check_cache_base_fp()", hasattr(M, "check_cache_base_fp"))
check("① 有 resolve_expect_fp()", hasattr(M, "resolve_expect_fp"))

# ---- 静态断言：argparse 与三处调用 ----
src = io.open(SRC, encoding="utf-8").read()
check("④ argparse 有 --expect-base-fp", '"--expect-base-fp"' in src)
check("④ argparse 有 --allow-cache-base-mismatch", '"--allow-cache-base-mismatch"' in src)
n_train = src.count('check_cache_base_fp(cache, *resolve_expect_fp(a)')
n_val = src.count('check_cache_base_fp(val_cache, *resolve_expect_fp(a)')
n_ref = src.count('check_cache_base_fp(ref_cache, *resolve_expect_fp(a)')
check("④ train/val/refusal 三处都接上", (n_train, n_val, n_ref) == (1, 1, 1),
      f"train={n_train} val={n_val} refusal={n_ref}")

FP_A = {"config16": "aaaaaaaaaaaaaaaa", "index16": "bbbbbbbbbbbbbbbb",
        "first_shard16": "cccccccccccccccc", "n_shards": 18}
FP_B = {"config16": "1111111111111111", "index16": "2222222222222222",
        "first_shard16": "3333333333333333", "n_shards": 18}


class FakeCache:
    def __init__(self, root, name="train-src"):
        self.specs = [{"name": name, "root": root}]


def make_cache(root, fp, name="train-src"):
    os.makedirs(root, exist_ok=True)
    with io.open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "/x", "model_fp": fp, "samples": ["a.pt"]}, f)
    return FakeCache(root, name)


def run(cache, expect, allow, src_tag="test"):
    try:
        M.check_cache_base_fp(cache, expect, src_tag, allow, "train")
        return True, ""
    except SystemExit as e:
        return False, str(e.code)


root = tempfile.mkdtemp(prefix="rg-t30-")
try:
    # ① 不符 → FATAL，且消息含两边 fp 与前 3 项
    c_bad = make_cache(os.path.join(root, "cache-v3"), FP_A)
    ok, msg = run(c_bad, FP_B, allow=False)
    check("① 指纹不符 → FATAL", ok is False, msg[:80])
    check("① 消息含 cache 指纹", "aaaaaaaaaaaaaaaa" in msg or "model_fp" in msg, msg[:120])
    check("① 消息含期望指纹", "1111111111111111" in msg or "期望" in msg, msg[:120])
    check("① 消息含「前 3 项」", "前 3 项" in msg, msg[-160:])
    check("① 消息含重建提示", "precompute_activations" in msg or "重建" in msg, msg[-120:])

    # ② 一致 → 通过
    c_ok = make_cache(os.path.join(root, "cache-v4"), FP_A)
    ok, msg = run(c_ok, FP_A, allow=False)
    check("② 指纹一致 → 通过", ok is True, msg)

    # ③ 逃生口 → 放行（不抛），且打印 WARNING（用捕获 stdout 验证）
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        ok, msg = run(c_bad, FP_B, allow=True)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    check("③ 逃生口放行", ok is True, msg)
    check("③ 放行有 WARNING", "WARNING" in out, out.strip().splitlines()[-1] if out else "")

    # ④ 缺 model_fp 的旧缓存 → FATAL（不许静默放行）
    c_old = os.path.join(root, "cache-old")
    os.makedirs(c_old, exist_ok=True)
    with io.open(os.path.join(c_old, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"model": "/x", "samples": ["a.pt"]}, f)
    ok, msg = run(FakeCache(c_old, "old-src"), FP_A, allow=False)
    check("④ 旧缓存缺 model_fp → FATAL", ok is False and "model_fp" in msg, msg[:100])

    # ④ 无 manifest → 只警告不 FATAL（该源可能是老数据，不阻断但要点名）
    c_noman = os.path.join(root, "cache-noman")
    os.makedirs(c_noman, exist_ok=True)
    ok, msg = run(FakeCache(c_noman, "noman"), FP_A, allow=False)
    check("④ 无 manifest → 不 FATAL（点名警告）", ok is True, msg)
finally:
    import shutil
    shutil.rmtree(root, ignore_errors=True)

print()
if fails:
    print(f"FAIL: {len(fails)} 项")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("PASS: 消费侧指纹守卫（不符 FATAL / 一致通过 / 逃生口有 WARNING / 旧缓存不放行）")
