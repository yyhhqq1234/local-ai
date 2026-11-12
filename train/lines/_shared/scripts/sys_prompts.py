# -*- coding: utf-8 -*-
"""system prompt 常量（单一真相源）

独立成文件的原因：训练数据替换脚本（replace_2a_system.py）只需要这个常量，
但 eval_2a_code.py 顶部 import torch —— 用 anaconda python 跑数据脚本时会
ModuleNotFoundError。把常量抽出来，两边都 import 这里，既保持单一真相源，
又不让数据脚本依赖 torch。
"""

# ── 2A 训练与评测共用的 system（2026-10-29 方案 A）──────────────────
# 为什么不用数据里原本的 "You are OpenHands agent..."：
#   2A 数据的 assistant 是长代码分析文本（P50 2476 字符，16195 条里仅 3 条含
#   <tool_call>，0 条多轮），但那个 system 会触发 base 模型（Qwen3.5-9B）预训练里的
#   OpenHands agent 记忆，模型于是去调 read/grep/pwsh 工具而不是写分析 —— 与数据
#   的期望行为冲突。
#   实测：原 system 下实体覆盖 24.8% / 代码块 2.5%；换成这个 system 后
#         60.0% / 40.0%（L1 68%/64%、L2 52%/29%、L3 60%/25%）。
SYSTEM_2A = (
    "You are a senior software engineer. When you are given a bug report or a code question, you:\n"
    "1. Identify the root cause precisely, naming the exact file, function and identifier involved.\n"
    "2. Give the concrete fix: show the code you would change, in a fenced code block.\n"
    "3. State how to verify the fix.\n"
    "Answer in the same language as the question. Do not ask for more information; reason from what is given."
)
