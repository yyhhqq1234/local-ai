#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t31_pack_config.py -- pack 里缺 config.json 必须 FATAL，不许 `else {}` 兜底。

缺陷现象
    split_merge_layers.py:
        cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        ...
        for name in (...):            # 元数据拷贝
            if os.path.exists(s): shutil.copy2(...)      # 缺了就静默跳过
后果
    ① adapter_config.json 缺失 → cfg={} → 后面 cfg.get(...) 全走默认值，
       合并比例/秩静默用错（包照样打出来、层数也对）；
    ② config.json 没进 pack → 下游 train_partial_lora 建不出骨架，
       本地训不起来，事后只能靠 deploy/fix_pack.sh 打补丁（v3 就是这么过的）。
    这是签名 S1（缺失被默认值吸收）在本仓的又一次复发。
正确的断言
    ① 缺 adapter_config.json → SystemExit（不是返回 {}；反向证明旧写法返回 {} 且不报）
    ② 元数据源缺 config.json → SystemExit，且报错里带源路径与"期望来源"
    ③ 正常源 → 拷齐 + 产物 config.json 回读 architectures 与源一致
    ④ 源 config 缺 architectures → 只 warn，不 FATAL（text 视图允许没有）
如果这条 FAIL 说明什么
    `else {}` 又回来了，或者 config.json 又变成"有就拷、没有也当没事"。
"""
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import types

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(KITTY, "scripts", "split_merge_layers.py")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load_mod(path, name):
    # 只给第三方库打桩（torch / safetensors），被测函数本身不碰它们。
    if "torch" not in sys.modules:
        m = types.ModuleType("torch")
        m.bfloat16 = "bfloat16"
        sys.modules["torch"] = m
    if "safetensors" not in sys.modules:
        st = types.ModuleType("safetensors")
        st.safe_open = object
        sys.modules["safetensors"] = st
        stt = types.ModuleType("safetensors.torch")
        stt.save_file = lambda *a, **k: None
        sys.modules["safetensors.torch"] = stt
        st.torch = stt
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    S = load_mod(SRC, "split_merge_t31")
    check("split_merge_layers 可 import（HEAD 里没有这把锁，检查不空跑）", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 split_merge_layers 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

root = tempfile.mkdtemp(prefix="rg-t31-")
try:
    # ① 缺 adapter_config.json
    adir = os.path.join(root, "adapter_no_cfg")
    os.makedirs(adir)
    open(os.path.join(adir, "adapter_model.safetensors"), "wb").write(b"\x00" * 64)
    try:
        S.load_adapter(adir)
        check("① 缺 adapter_config.json → FATAL", False, "没有任何异常，静默返回了")
    except SystemExit as e:
        msg = str(e)
        check("① 缺 adapter_config.json → FATAL", True, msg.splitlines()[0][:70])
        check("① 报错带路径", "adapter_config.json" in msg, "")
        check("① 报错说清期望来源", "adapter" in msg and "期望来源" in msg, "")

    # ①b 反向：旧写法对同一目录返回 {} 且不报（证明断言不是空跑）
    cfg_path = os.path.join(adir, "adapter_config.json")
    old_cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    check("① 反向：旧写法返回空 dict（= 当年静默用默认值）", old_cfg == {}, str(old_cfg))

    # ② 元数据源缺 config.json
    src = os.path.join(root, "src_no_cfg")
    out = os.path.join(root, "out1")
    os.makedirs(src)
    os.makedirs(out)
    open(os.path.join(src, "tokenizer.json"), "w", encoding="utf-8").write("{}")
    try:
        S.copy_meta(src, out)
        check("② 源缺 config.json → FATAL", False, "没有异常，config 又静默漏了")
    except SystemExit as e:
        msg = str(e)
        check("② 源缺 config.json → FATAL", True, msg.splitlines()[0][:70])
        check("② 报错带源路径", src in msg, "")
        check("② 报错说明后果/期望来源",
              "期望来源" in msg and ("pack" in msg or "训不起来" in msg), "")

    # ③ 正常源
    src2 = os.path.join(root, "src_ok")
    out2 = os.path.join(root, "out2")
    os.makedirs(src2)
    os.makedirs(out2)
    cfg = {"architectures": ["Qwen3_5ForCausalLM"], "model_type": "qwen3_5"}
    with io.open(os.path.join(src2, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    with io.open(os.path.join(src2, "tokenizer.json"), "w", encoding="utf-8") as f:
        json.dump({"v": 1}, f)
    with io.open(os.path.join(src2, "chat_template.jinja"), "w", encoding="utf-8") as f:
        f.write("{{x}}")
    got = S.copy_meta(src2, out2)
    check("③ 正常源 → 返回 copied 清单（3 个）", len(got["copied"]) == 3, str(got["copied"]))
    with io.open(os.path.join(out2, "config.json"), encoding="utf-8") as f:
        prod = json.load(f)
    check("③ 产物里真能读到 architectures", prod.get("architectures") == ["Qwen3_5ForCausalLM"],
          str(prod.get("architectures")))
    check("③ 返回值里的 architectures 与产物一致",
          got["architectures"] == prod.get("architectures"), str(got["architectures"]))
    check("③ tokenizer 也带上了", os.path.isfile(os.path.join(out2, "tokenizer.json")))

    # ④ 源 config 没有 architectures → 只 warn
    src3 = os.path.join(root, "src_bare")
    out3 = os.path.join(root, "out3")
    os.makedirs(src3)
    os.makedirs(out3)
    with io.open(os.path.join(src3, "config.json"), "w", encoding="utf-8") as f:
        json.dump({"model_type": "qwen3_5"}, f)
    try:
        r3 = S.copy_meta(src3, out3)
        check("④ 缺 architectures 不 FATAL", r3["architectures"] is None, str(r3))
    except SystemExit as e:
        check("④ 缺 architectures 不 FATAL", False, str(e)[:60])

    # ⑤ 源码静态：不许再有 `else {}` 兜 cfg、copy 走 copy_meta
    src_txt = open(SRC, encoding="utf-8").read()
    body = src_txt.split("def load_adapter")[1].split("def copy_meta")[0]
    check("⑤ 源码 body 里没有 `if os.path.exists(cfg_path) else {}`",
          "else {}" not in body.replace("if exists else {}", ""))
    check("⑤ main 里改成调 copy_meta", "copy_meta(src, out)" in src_txt)
    check("⑤ copy_meta 有 config.json 必需清单", 'required=("config.json",)' in src_txt)
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nPASS: 缺 adapter_config/缺 config.json 都 FATAL，正常源拷齐且产物可回读 architectures"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
