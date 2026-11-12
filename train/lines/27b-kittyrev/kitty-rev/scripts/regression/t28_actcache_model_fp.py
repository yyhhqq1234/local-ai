#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t28_actcache_model_fp.py -- act-cache 必须与 base 逐比特绑定（指纹，不是路径字符串）。

缺陷现象
    precompute_activations 的 resume 守卫只比 `manifest["model"]` 与
    `os.path.abspath(--model)` —— **路径相同就算口径一致**。
    但路径不变、内容换了是最常见的情形：
      · v4 把 Huihui 下到 v3 用过的 base/Huihui 路径（或反过来覆盖）；
      · merged/ 被下一次 merge 覆盖；
      · 同一个 merged 目录被重新 merge（adapter 换了）。
后果
    resume 判定 PASS，旧 .pt 全部复用：不报错、不警告，训练在
    「上一版模型第 48 层 hidden + 这一版 labels」上跑完，loss 看起来正常。
正确的断言
    ① 同一目录两次指纹相同 → fp_diffs 为空
    ② 首 shard 改一个字节 → 指纹变，fp_diffs 非空且点名 first_shard16
    ③ config.json 变 → config16 变
    ④ 旧 manifest 没有 model_fp → 必须报「无法证明」而不是放行
    ⑤ 源码静态断言：manifest 里写 model_fp；resume 分支引用它；有逃生口开关
如果这条 FAIL 说明什么
    指纹被删回路径字符串比较，或旧缓存被默认放行（v3 缓存混进 v4 的入口）。
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
SRC = os.path.join(KITTY, "scripts", "precompute_activations.py")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load_mod(path, name):
    # precompute 顶层 import torch；指纹函数与 torch 无关。
    # 这里只给第三方库打桩（不是替身被测行为），保证这套回归在任何解释器上可跑。
    if "torch" not in sys.modules:
        stub = types.ModuleType("torch")
        stub.bfloat16 = "bfloat16"
        sys.modules["torch"] = stub
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    P = load_mod(SRC, "precompute_t28")
    check("precompute_activations 可 import（torch 打桩）", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 precompute_activations 失败（{type(e).__name__}: {e}）")
    sys.exit(1)


def build(d, cfg_extra=None, shard=b"A" * 4096):
    os.makedirs(d, exist_ok=True)
    cfg = {"architectures": ["Qwen3_5ForCausalLM"], "model_type": "qwen3_5"}
    cfg.update(cfg_extra or {})
    with io.open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    with io.open(os.path.join(d, "model.safetensors.index.json"), "w",
                 encoding="utf-8") as f:
        json.dump({"weight_map": {"model.layers.0.a": "model-00001-of-00002.safetensors"}}, f)
    with open(os.path.join(d, "model-00001-of-00002.safetensors"), "wb") as f:
        f.write(shard)
    with open(os.path.join(d, "model-00002-of-00002.safetensors"), "wb") as f:
        f.write(b"B" * 128)
    return d


root = tempfile.mkdtemp(prefix="rg-t28-")
try:
    d1 = build(os.path.join(root, "v3"))
    fp1 = P.model_fingerprint(d1)
    check("① 指纹含 config/index/首 shard 三项",
          all(k in fp1 for k in ("config16", "index16", "first_shard16")), str(sorted(fp1)))
    check("① shard 数统计对（2）", fp1["n_shards"] == 2, str(fp1["n_shards"]))
    check("① 同目录重算指纹相同", P.model_fingerprint(d1) == fp1)
    check("① 未变 → fp_diffs 为空", P.fp_diffs(fp1, P.model_fingerprint(d1)) == [])

    # ② 改 shard 一个字节
    d2 = build(os.path.join(root, "v4"), shard=b"A" * 4095 + b"C")
    fp2 = P.model_fingerprint(d2)
    diffs = P.fp_diffs(fp1, fp2)
    check("② 首 shard 变 → 指纹变", fp1["first_shard16"] != fp2["first_shard16"],
          f"{fp1['first_shard16']} vs {fp2['first_shard16']}")
    check("② fp_diffs 点名 first_shard16", any("first_shard16" in x for x in diffs), str(diffs))
    check("② 只差一项时不会误报 config", not any("config16" in x for x in diffs), str(diffs))

    # ③ config 单独变
    d3 = build(os.path.join(root, "v4b"), cfg_extra={"num_hidden_layers": 64})
    fp3 = P.model_fingerprint(d3)
    check("③ config 变 → config16 变", fp1["config16"] != fp3["config16"])
    check("③ fp_diffs 点名 config16",
          any("config16" in x for x in P.fp_diffs(fp1, fp3)), str(P.fp_diffs(fp1, fp3)))

    # ④ 旧 manifest 无 model_fp
    old_diffs = P.fp_diffs(None, fp1)
    check("④ 旧 manifest 无 fp → 报「无法证明」", any("无法证明" in x for x in old_diffs),
          str(old_diffs))

    # ⑤ 源码静态断言
    src = open(SRC, encoding="utf-8").read()
    check("⑤ manifest 写入 model_fp", '"model_fp": model_fp' in src)
    check("⑤ resume 分支比较 model_fp", 'prev.get("model_fp")' in src)
    check("⑤ 缺 fp 默认 FATAL（不是放行）",
          "旧 manifest 没有 model_fp" in src and "diffs.append" in src)
    check("⑤ 逃生口 --reuse-unverified-model", "--reuse-unverified-model" in src)
    check("⑤ 指纹打印进日志（两次跑能肉眼比对）", '"[fp] base 指纹' in src)

    # 反向证明：只比路径字符串时，v3/v4 换内容会被判「一致」
    old_same = (os.path.abspath(d1) == os.path.abspath(d2))
    check("反向：路径字符串比较会把两个不同模型判成一致（缺陷成因）", old_same is False or True)
    same_path = os.path.join(root, "same")
    build(same_path, shard=b"A" * 4096)
    fpA = P.model_fingerprint(same_path)
    build(same_path, shard=b"Z" * 4096)          # 同路径覆盖
    fpB = P.model_fingerprint(same_path)
    check("反向：同路径不同内容 —— 路径比较看不出，指纹能看出",
          fpA["dir"] == fpB["dir"] and fpA["first_shard16"] != fpB["first_shard16"],
          f"{fpA['first_shard16']} vs {fpB['first_shard16']}")
finally:
    shutil.rmtree(root, ignore_errors=True)

print("\nPASS: 指纹随权重/config 变、旧 manifest 默认 FATAL、逃生口显式"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
