# -*- coding: utf-8 -*-
"""patch_traj_intent.py — 根治「空 assistant content」先验（塌陷主因）

证据（2026-11-02）
  gen4 数据里 assistant 消息共 27,806 条，其中 **5,390 条 content 为空（19.4%）** ——
  这些全是轨迹里的 tool_calls 步。也就是说模型每 5 个回答里就有 1 个被教成「什么都不输出」。
  实测后果：门控 32 条里 20 条空回复；NSFW 提示下先输出一段自编 preamble 再 EOS。

修法
  轨迹里每一步 tool_call 的 assistant 都补一句**动作意图**（多样化短句），
  既保留 tool_calls 结构教学，又不产生「空回答」样本。
  最终收尾那句也保留（一句结论），形成「意图 → 调用 → 结论」的正常形态。
"""
import json
import random
import re

p = 'train/lines/_shared/scripts/build_kitty_traj.py'
s = open(p, encoding='utf-8').read()

INTENT = '''
INTENT_TPL = (
    "先确认{}.", "这一步用{}。", "调{}看一下。", "先用{}拿基础信息。",
    "接下来{}。", "换{}继续。", "{}走一次。", "用{}核对一遍。",
)
'''
if 'INTENT_TPL' not in s:
    s = s.replace('ERR = {', INTENT.strip() + '\n\nERR = {')
    print('added INTENT_TPL')

old = '''        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": tool, "arguments": args}}]})'''
new = '''        # 关键：content 不能为空，否则训练出「空回答」先验（gen4 塌陷主因，5,390/27,806=19.4%）
        _intent = rnd.choice(INTENT_TPL).format(tool)
        msgs.append({"role": "assistant", "content": _intent,
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": tool, "arguments": args}}]})'''
if old in s:
    s = s.replace(old, new)
    print('patched chain steps')

# 单工具覆盖行同样处理
old2 = '''                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": call_id, "type": "function",
                                 "function": {"name": name, "arguments": args}}]},'''
new2 = '''                {"role": "assistant", "content": rnd.choice(INTENT_TPL).format(name),
                 "tool_calls": [{"id": call_id, "type": "function",
                                 "function": {"name": name, "arguments": args}}]},'''
if old2 in s:
    s = s.replace(old2, new2)
    print('patched single-tool rows')

open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('done')
