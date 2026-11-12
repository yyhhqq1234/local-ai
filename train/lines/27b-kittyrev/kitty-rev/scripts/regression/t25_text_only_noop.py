#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t25_text_only_noop.py -- `--text-only` 是 no-op 时必须打出来，不许静默。

缺陷现象
    train_kitty.py 里：
        if a.text_only:
            if hasattr(_cfg, "language_model_only"):
                _cfg.language_model_only = True
                print("[load] text-only: 只加载文本塔（跳过 vision）")
    transformers 5.20.2 的 Qwen3_5 配置**没有** language_model_only（grep 0 命中）
    → hasattr 恒 False → **一行都不打印**。参数被接受、命令 rc=0、
    报告里写着「--text-only 已跳过 vision」——而实际什么都没发生。
后果
    把「配置层已跳过 vision」当既定事实写进结论（v4 报告的核心假设之一）；
    真正该看的判据（加载后 visual/vision 模块数 = 0）没人看。
正确的断言
    ① 无该字段的 config → supported=False 且 note 里必须出现 no-op 与「证据」字样
    ② 有该字段的 config → applied=True 且 cfg 真被设成 True
    ③ 字段存在但赋值抛异常 → supported=True / applied=False（不吞异常）
    ④ visual_modules() 能数个准：混入 model.visual.* 必须被点到
    ⑤ 源码静态断言：no-op 分支必须打 [WARN]；加载后必须打 [verify]（防有人再删）
如果这条 FAIL 说明什么
    又变回静默 no-op，或把「没生效」当成了「已生效」。
"""
import importlib.util
import os
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
    T = load_mod(SRC, "train_kitty_t25")
    check("train_kitty 可 import（--help 级验证）", True)
except Exception as e:                                        # noqa: BLE001
    print(f"\nFAIL: 载入 train_kitty 失败（{type(e).__name__}: {e}）")
    sys.exit(1)


class CfgNoField:
    pass


class CfgWithField:
    language_model_only = False


class CfgRaising:
    @property
    def language_model_only(self):
        return False

    def __setattr__(self, k, v):
        raise RuntimeError("read-only config")


# ① 无字段（= transformers 5.20.2 的现实）
r = T.text_only_patch(CfgNoField())
check("① supported=False", r["supported"] is False, str(r))
check("① applied=False", r["applied"] is False, str(r))
check("① note 明说 no-op", "no-op" in r["note"], r["note"][:40])
check("① note 给出真判据（不许只说“不影响”）", "真判据" in r["note"] or "判据" in r["note"],
      r["note"][-40:])

# ② 有字段
c = CfgWithField()
r = T.text_only_patch(c)
check("② applied=True", r["applied"] is True, str(r))
check("② 字段真的被设成 True", c.language_model_only is True, str(c.language_model_only))

# ③ 赋值失败不吞
r = T.text_only_patch(CfgRaising())
check("③ 赋值失败 → applied=False 且带原因", r["applied"] is False and "失败" in r["note"],
      str(r))

# ④ visual_modules 计数
names = ["model.visual.blocks.0.attn.q_proj", "visual.merger.mlp.0",
         "model.language_model.layers.0.self_attn.q_proj", "lm_head"]
got = T.visual_modules(names)
check("④ 视觉模块被抓到（2 个）", len(got) == 2, str(got))
check("④ 文本层不误伤", all("language_model" not in g for g in got), str(got))

# ⑤ 源码静态断言（防回退成静默）
src = open(SRC, encoding="utf-8").read()
check("⑤ 源码有 no-op 的 [WARN] 输出", "[WARN] --text-only 未生效" in src)
check("⑤ 源码加载后有 [verify] 实测行", "[verify] text-only" in src)
check("⑤ --text-only 的 help 已注明 no-op", "--text-only" in src and "no-op" in src)


# 反向证明：旧实现遇到无字段的 config 是彻底静默的（断言不是空跑）
def old_impl(cfg):
    out = []
    if hasattr(cfg, "language_model_only"):
        cfg.language_model_only = True
        out.append("text-only: 只加载文本塔")
    return out


check("反向：旧实现对该 config 输出为空（= 当年就是这么静默的）",
      old_impl(CfgNoField()) == [])

print("\nPASS: no-op 被显式报出、真判据（visual 模块数）可测、源码不许回退成静默"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
