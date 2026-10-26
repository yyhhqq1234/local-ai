#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t24_pin_arch.py -- merged 的 architectures 必须在 convert 前钉住，且幂等、无 .bak。

缺陷现象
    merge（纯 text）出来的目录只有 text 张量，但 config.json 的
    `architectures` 仍是 `["Qwen3_5ForConditionalGeneration"]`（VL 包装）；
    convert_hf_to_gguf 按 architectures 选分支 → 走 VL 分支：
    张量集合/前缀不对、或抛 KeyError 后换参数重试（换成了 text 分支也没人察觉）。
后果
    GGUF 能写出来、inspect 也能过，只有「张量数/前缀」能暴露；v4 头号静默错。
正确的断言
    ① 缺 config.json → rc=2（没有配置不许进 convert）
    ② 未 pin + --check → rc=1，且提示未 pinned
    ③ pin 后回读两个字段都对；目录里**没有** .bak/.tmp；再跑一次 sha16 不变（幂等）
    ④ 反向证明：不 pin 的 config 用同一个 readback 判定必须 False（断言不是空跑）
如果这条 FAIL 说明什么
    pin 步骤被删/被改成只写一个字段/开始留备份，或 --check 不再能拦住未 pin 的目录。
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# 控制台是 GBK(cp936) 时，打印子进程输出里的 ✓/✗ 会抛 UnicodeEncodeError
# → 变成假 FAIL（与 run_all.py 里那条「假失败」缺陷同源）。自己先钉死 utf-8。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # 非 TextIOWrapper 时跳过
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(KITTY, "scripts", "pin_arch.py")
PY = sys.executable
fails = []


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


try:
    P = load_mod(SCRIPT, "pin_arch_t24")
    check("pin_arch 可 import（py_compile 过不代表能 import）", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 pin_arch 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

VL_CFG = {"architectures": ["Qwen3_5ForConditionalGeneration"],
          "model_type": "qwen3_5",
          "text_config": {"architectures": ["Qwen3_5ForConditionalGeneration"],
                          "num_hidden_layers": 64},
          "vision_config": {"depth": 27}}


def mkdir(cfg=None, index=None, shard=b"\x00" * 64):
    d = tempfile.mkdtemp(prefix="rg-t24-")
    if cfg is not None:
        with io.open(os.path.join(d, "config.json"), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)
    if index is not None:
        with io.open(os.path.join(d, "model.safetensors.index.json"), "w",
                     encoding="utf-8") as f:
            json.dump(index, f)
    if shard is not None:
        with open(os.path.join(d, "model-00001-of-00018.safetensors"), "wb") as f:
            f.write(shard)
    return d


def run(d, *extra):
    p = subprocess.run([PY, SCRIPT, "--dir", d, *extra], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                       timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


dirs = []
try:
    # ① 缺 config
    d = mkdir(cfg=None, shard=None)
    dirs.append(d)
    rc, out = run(d)
    check("① 缺 config.json → rc=2", rc == 2, f"rc={rc}")
    check("① 缺 config.json → 说清是缺配置", "config.json" in out, out.strip().splitlines()[:1])

    # ② 未 pin + --check → 红
    d = mkdir(cfg=dict(VL_CFG))
    dirs.append(d)
    rc, out = run(d, "--check")
    check("② 未 pin + --check → rc=1", rc == 1, f"rc={rc}")
    check("② 未 pin → 提示 pin（convert 会走 VL 分支）",
          "未 pinned" in out and ("VL" in out or "坑 c" in out), out.strip().splitlines()[:1])
    with io.open(os.path.join(d, "config.json"), encoding="utf-8") as f:
        still = json.load(f)
    check("② --check 不写盘", still == VL_CFG, f"arch={still.get('architectures')}")

    # ③ 真 pin：回读 + 无备份 + 幂等
    idx = {"weight_map": {"model.language_model.layers.0.self_attn.q_proj.weight":
                          "model-00001-of-00018.safetensors"}}
    d = mkdir(cfg=dict(VL_CFG), index=idx)
    dirs.append(d)
    rc, out = run(d, "--index")
    check("③ pin → rc=0", rc == 0, f"rc={rc}")
    with io.open(os.path.join(d, "config.json"), encoding="utf-8") as f:
        got = json.load(f)
    check("③ architectures 已 pin", got.get("architectures") == ["Qwen3_5ForCausalLM"],
          str(got.get("architectures")))
    check("③ text_config.architectures 已 pin",
          (got.get("text_config") or {}).get("architectures") == ["Qwen3_5ForCausalLM"],
          str((got.get("text_config") or {}).get("architectures")))
    leftovers = [n for n in os.listdir(d) if ".bak" in n or ".tmp." in n]
    check("③ 不留 .bak/.tmp（体积 ×2 禁止）", not leftovers, str(leftovers))
    sha1 = P.sha16(os.path.join(d, "config.json"))
    rc2, out2 = run(d)
    sha2 = P.sha16(os.path.join(d, "config.json"))
    check("③ 幂等：第二次 rc=0 且 sha16 不变", rc2 == 0 and sha1 == sha2, f"{sha1} → {sha2}")
    check("③ 第二次打「已 pinned」", "已 pinned" in out2, out2.strip().splitlines()[:1])
    check("③ 视觉张量统计会打印（纯文本应有 0）", "[index] 视觉张量数=0" in out,
          out.strip().splitlines()[:2])

    # ④ 反向证明：不 pin 的 config 必须被判 False
    ok_bad, _, _ = P.readback_ok(os.path.join(mkdir(cfg=dict(VL_CFG)), "config.json"))
    check("④ 未 pin 的 config 回读判定 = False（断言不是空跑）", ok_bad is False, str(ok_bad))
    d = mkdir(cfg=dict(VL_CFG))
    dirs.append(d)
    changed, before = P.pin_cfg(json.loads(json.dumps(VL_CFG)))
    check("④ pin_cfg 报出两个字段都变了", len(changed) == 2, str([c[0] for c in changed]))
    check("④ before 保留旧值（可写进报告）",
          before["architectures"] == ["Qwen3_5ForConditionalGeneration"], str(before))

    # ⑤ 视觉张量计数（判据，不是装饰）
    n, names = P.vision_tensor_count({"weight_map": {
        "model.visual.blocks.0.attn.q_proj.weight": "s0",
        "model.language_model.layers.0.self_attn.q_proj.weight": "s0"}})
    check("⑤ 视觉张量被抓到（1 个）", n == 1, f"n={n} {names}")
    n0, _ = P.vision_tensor_count({"weight_map": {
        "model.language_model.layers.0.self_attn.q_proj.weight": "s0"}})
    check("⑤ 纯文本 merge 计 0", n0 == 0, f"n={n0}")
finally:
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)

print("\nPASS: pin_arch 拦缺配置 / 拦未 pin / 幂等无备份 / 视觉张量可判"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
