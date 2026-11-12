#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t3_mask_batch_encoding.py -- assistant 掩码必须真的盖住 assistant 正文。

缺陷现象（两个叠在一起，任一都致命）
    ① transformers 5.x 的 apply_chat_template(tokenize=True) 返回 BatchEncoding，
       len() 是字段数而不是 token 数 → 前缀比较全失败；
    ② 就算取对 id，"累计前缀是全文 token 前缀"这个假设对本模板也不成立
       （生成提示多吐一个标记，它和换行会合并成另一个 token）。
    两者合起来：每个 assistant 段判 bad → labels 全 -100 → 兜底成"只训最后一个
    token"，全程不报错。
后果
    --mask assistant 训出来的 adapter 只学了"预测句尾"，其余 token 不计损失。
正确的断言
    _as_ids 能从 dict/BatchEncoding 取出 ids（不是键）；
    assistant_mask 的 ok_spans>=1、bad=0，且 mask 覆盖的 token 解码回来 == 正文。
如果这条 FAIL 说明什么
    掩码又退回前缀法了，或者标签不再与正文对齐 —— 先看 assistant_mask 走哪条路径。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(KITTY, "scripts"))

import precompute_activations as P  # noqa: E402


class FakeTok:
    """最小假 tokenizer：字符/标签级 + 一条跨边界合并（模拟 BPE merge）。

    渲染：<u>..</u><a>..</a>；生成提示在末尾多吐一个 "\\n"。
    合并规则：["</u>", "\\n"] → 一个 token。于是「前缀 token 序列」不是
    「全文 token 序列」的前缀，前缀法必然错位（真实模板的 <think>\\n 就是这形态）。
    """

    def __init__(self):
        self.vocab, self.inv = {}, {}

    def _id(self, unit):
        if unit not in self.vocab:
            i = 100 + len(self.vocab)
            self.vocab[unit] = i
            self.inv[i] = unit
        return self.vocab[unit]

    def _units(self, s):
        out, i, tags = [], 0, ("<u>", "</u>", "<a>", "</a>")
        while i < len(s):
            for t in tags:
                if s.startswith(t, i):
                    out.append(t)
                    i += len(t)
                    break
            else:
                out.append(s[i])
                i += 1
        return out

    def _encode(self, s):
        units = self._units(s)
        merged, i = [], 0
        while i < len(units):
            if i + 1 < len(units) and units[i] == "</u>" and units[i + 1] == "\n":
                merged.append("</u>\n")          # ← 跨边界合并
                i += 2
            else:
                merged.append(units[i])
                i += 1
        spans, pos = [], 0
        for u in merged:
            spans.append((pos, pos + len(u)))
            pos += len(u)
        return [self._id(u) for u in merged], spans

    def render(self, msgs, add_generation_prompt=False):
        s = "".join("<%s>%s</%s>" % (m["role"][0], m["content"], m["role"][0])
                    for m in msgs)
        return s + ("\n" if add_generation_prompt else "")

    def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=False):
        s = self.render(msgs, add_generation_prompt)
        if not tokenize:
            return s
        ids, _ = self._encode(s)
        return {"input_ids": ids}                # ← BatchEncoding 同款

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        ids, spans = self._encode(text)
        out = {"input_ids": ids}
        if return_offsets_mapping:
            out["offset_mapping"] = spans
        return out

    def decode(self, ids, skip_special_tokens=True):
        return "".join(self.inv[i] for i in ids)


def old_mask_raw(tok, messages, n_ids, full_ids):
    """旧实现原样：len()/list() 直接作用在 BatchEncoding 上。"""
    keep, ok, bad = [False] * n_ids, 0, 0
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        pre = tok.apply_chat_template(messages[:i], tokenize=True, add_generation_prompt=True)
        upto = tok.apply_chat_template(messages[:i + 1], tokenize=True, add_generation_prompt=False)
        a, b = len(pre), len(upto)
        if a >= b or b > n_ids or list(full_ids[:a]) != list(pre):
            bad += 1
            continue
        for j in range(a, b):
            keep[j] = True
        ok += 1
    return keep, ok, bad


def old_mask_prefix(tok, messages, n_ids, full_ids):
    """只修了取 id 口径、仍用前缀法的中间版本（用来单独证明缺陷②）。"""
    keep, ok, bad = [False] * n_ids, 0, 0
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        pre = P._as_ids(tok.apply_chat_template(messages[:i], tokenize=True,
                                               add_generation_prompt=True))
        upto = P._as_ids(tok.apply_chat_template(messages[:i + 1], tokenize=True,
                                                add_generation_prompt=False))
        a, b = len(pre), len(upto)
        if a >= b or b > n_ids or list(full_ids[:a]) != list(pre):
            bad += 1
            continue
        for j in range(a, b):
            keep[j] = True
        ok += 1
    return keep, ok, bad


msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
tok = FakeTok()
full_text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
full_ids = tok(full_text)["input_ids"]

fails = []

if P._as_ids({"input_ids": [7, 8, 9]}) != [7, 8, 9]:
    fails.append("_as_ids 没从 dict 取 input_ids")
print(f"[ids  ] _as_ids({{'input_ids':[7,8,9]}}) = {P._as_ids({'input_ids': [7, 8, 9]})}")

_, ok_raw, bad_raw = old_mask_raw(tok, msgs, len(full_ids), full_ids)
print(f"[old①] BatchEncoding 直取 → ok={ok_raw} bad={bad_raw}（应 ok=0）")
if ok_raw != 0:
    fails.append("假 tokenizer 没复现缺陷①")

_, ok_pre, bad_pre = old_mask_prefix(tok, msgs, len(full_ids), full_ids)
print(f"[old②] 取对 id 但用前缀法 → ok={ok_pre} bad={bad_pre}（应 ok=0）")
if ok_pre != 0:
    fails.append("假 tokenizer 没复现缺陷②（合并规则没生效）")

keep, ok, bad = P.assistant_mask(tok, msgs, len(full_ids), full_ids, full_text=full_text)
covered = tok.decode([full_ids[j] for j in range(len(full_ids)) if keep[j]]).strip()
print(f"[new  ] ok={ok} bad={bad} covered={covered!r}（应为 'yo'）")
if ok < 1 or bad != 0:
    fails.append(f"新实现 ok={ok} bad={bad}")
if covered != "yo":
    fails.append(f"掩码覆盖 {covered!r}，不是 assistant 正文")

print("\nPASS: 掩码精确覆盖 assistant 正文（旧的两条路径都确实会退化）"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
