#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t26_lora_target_audit.py -- peft 的 list 型 target_modules 是后缀匹配，必须审计。

缺陷现象
    LoraConfig(target_modules=["q_proj", ...]) 走
    peft::check_target_module_exists → `key.endswith(f".{k}")`。
    后缀匹配**不看前缀**：`model.visual.blocks.0.attn.q_proj` 也会命中。
    v3 的 27B 里没有 visual 模块，所以没炸；v4 基座是 VL 包装模型，
    一旦按 ConditionalGeneration 加载（或审计缺失时换了加载方式），
    每个 vision block 白挂 4 个 LoRA —— trainable 数字变了，日志里只有一个总数。
后果
    「trainable = 79,691,776 所以与 v3 可比」这个验收前提被悄悄破坏；
    多出来的 LoRA 只吃不更新，还可能把 vision 层带歪。
正确的断言
    ① 干净模块表 → extra 为空，n_ends == n_strict
    ② 混入 model.visual.*.q_proj → extra 非空且点名（后缀命中的证据）
    ③ 带 base_model.model. 前缀的合法层 → 仍算 strict（白名单不能太窄）
    ④ 源码静态断言：勾 LoRA 之前必须调 lora_target_audit，且默认 fatal
如果这条 FAIL 说明什么
    审计被删/被绕过，后缀误挂又变成静默。
"""
import importlib.util
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(KITTY, "scripts", "train_kitty.py")
fails = []


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


try:
    T = load_mod(SRC, "train_kitty_t26")
    check("train_kitty 可 import", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 train_kitty 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

CLEAN = []
for i in range(3):
    for proj in ("q_proj", "k_proj", "v_proj", "o_proj",
                 "gate_proj", "up_proj", "down_proj"):
        CLEAN.append(f"model.language_model.layers.{i}.self_attn.{proj}"
                     if proj.endswith(("q_proj", "k_proj", "v_proj", "o_proj"))
                     else f"model.language_model.layers.{i}.mlp.{proj}")
CLEAN += ["model.language_model.embed_tokens", "lm_head", "model.visual"]

# ① 干净
a = T.lora_target_audit(CLEAN)
check("① extra 为空", a["extra"] == [], str(a["extra"]))
check("① 21 个挂点全在 strict 内（3 层 × 7）", a["n_ends"] == a["n_strict"] == 21,
      f"ends={a['n_ends']} strict={a['n_strict']}")
check("① 名字以 .mm / visual 结尾的不算挂点", "model.visual" not in a["ends"])

# ② 混入 VL 模块（后缀陷阱）
poison = CLEAN + [f"model.visual.blocks.{i}.attn.{p}"
                  for i in range(2) for p in ("q_proj", "k_proj", "v_proj", "o_proj")]
b = T.lora_target_audit(poison)
check("② 误命中被抓到（8 个）", len(b["extra"]) == 8, f"extra={len(b['extra'])}")
check("② 点名到具体模块", any("visual" in x for x in b["extra"]), str(b["extra"][:2]))
check("② 后缀命中数 > 白名单数（判据有区分度）", b["n_ends"] > b["n_strict"],
      f"{b['n_ends']} vs {b['n_strict']}")

# ③ 前缀宽容度：PeftModel 包装层/纯 text 视图都算合法
ok_names = ["base_model.model.layers.0.self_attn.q_proj",
            "model.layers.1.mlp.down_proj",
            "model.language_model.layers.2.linear_attn.v_proj"]
c = T.lora_target_audit(ok_names)
check("③ 三种合法前缀都被接受", c["extra"] == [] and c["n_strict"] == 3,
      f"strict={c['n_strict']} extra={c['extra']}")

# ④ 源码静态断言：审计在挂载之前，且默认 fatal
src = open(SRC, encoding="utf-8").read()
i_aud = src.find("_aud = lora_target_audit(")
i_lor = src.find("target_modules=TARGET_MODULES")
check("④ 审计出现在 LoraConfig 之前", 0 < i_aud < i_lor, f"audit@{i_aud} lora@{i_lor}")
check("④ 默认 fatal（误挂默认拒绝起训）", 'default="fatal"' in src)
check("④ 有逃生口 --lora-audit", "--lora-audit" in src and '"warn"' in src)

# 反向证明：只看「后缀命中了几个」的旧写法，对 VL 污染毫无反应
old_count = len([n for n in poison if n.rsplit(".", 1)[-1] in T.TARGET_MODULES])
check("反向：旧写法只报总数（29），看不出 8 个是 vision",
      old_count == 29 and len(b["extra"]) == 8, f"old={old_count}")
check("反向：旧写法的正则锚点（.*$）也能过 —— 证明必须用 fullmatch 白名单",
      bool(re.match(r".*(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$",
                    "model.visual.blocks.0.attn.q_proj")))

print("\nPASS: 后缀误挂可判、合法前缀不误伤、审计在挂载前且默认 fatal"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
