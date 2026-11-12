# -*- coding: utf-8 -*-
"""check_packing_wiring.py —— 只做接线自检，不训练、不碰 GPU、不加载模型

校验两件事：
  1 SFTConfig 能接受 packing=True / packing_strategy="bfd" / padding_free=True / pad_to_multiple_of
  2 trl 的 DataCollatorForLanguageModeling(padding_free=True, return_position_ids=True)
    真的产出 causal_conv1d varlen 要的三个键：cu_seq_lens_q/k、position_ids（逐段复位）、seq_idx
"""
import sys

import torch

from trl import SFTConfig
from trl.trainer.sft_trainer import DataCollatorForLanguageModeling

FAILS = []


def check(name, ok, detail=""):
    print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", name, detail))
    if not ok:
        FAILS.append(name)


print("== 1 SFTConfig 字段 ==")
for tag, kw in (
    ("packing=0 现状", dict(packing=False, padding_free=False)),
    ("packing=1 三开关", dict(packing=True, packing_strategy="bfd", padding_free=True,
                          pad_to_multiple_of=8, max_length=2048)),
):
    try:
        cfg = SFTConfig(output_dir="_work/_check_out", report_to="none", **kw)
        check("SFTConfig 接受 %s" % tag, True,
              "packing=%s padding_free=%s strategy=%s max_length=%s"
              % (cfg.packing, cfg.padding_free, cfg.packing_strategy, cfg.max_length))
    except Exception as e:                                                # noqa: BLE001
        check("SFTConfig 接受 %s" % tag, False, repr(e))

print("\n== 2 collator 产物 ==")
lens = [37, 58, 21]
examples = [{"input_ids": list(range(100, 100 + n)), "labels": list(range(100, 100 + n))} for n in lens]
for tag, coll in (
    ("现状（padding 批）", DataCollatorForLanguageModeling(pad_token_id=0)),
    ("三开关（拼包）", DataCollatorForLanguageModeling(
        pad_token_id=0, padding_free=True, return_position_ids=True)),
):
    b = coll(examples)
    keys = sorted(b.keys())
    print("  %-14s keys=%s" % (tag, keys))
    need = {"input_ids", "labels", "position_ids", "cu_seq_lens_q", "cu_seq_lens_k", "seq_idx",
            "max_length_q", "max_length_k"}
    if tag.startswith("三开关"):
        check("拼包产出 varlen 三键齐全", need <= set(keys), "缺 %s" % (need - set(keys)))
        total = b["input_ids"].shape[1]
        cu = b["cu_seq_lens_q"].tolist()
        check("cu_seq_lens 覆盖全长", cu[0] == 0 and cu[-1] == total, str(cu))
        check("cu_seq_lens 段数对", len(cu) - 1 == len(lens), "%d 段 / 期望 %d" % (len(cu) - 1, len(lens)))
        pos = b["position_ids"][0].tolist()
        check("position_ids 逐段复位", [pos[o] for o in cu[:-1]] == [0] * len(lens),
              "段首位置=%s" % [pos[o] for o in cu[:-1]])
        si = b["seq_idx"][0].tolist()
        check("seq_idx 每段一致", all(si[cu[i]:cu[i + 1]] == [i] * (cu[i + 1] - cu[i]) for i in range(len(lens))),
              "seq_idx=%s" % si)
        check("seq_idx 是 int32", b["seq_idx"].dtype == torch.int32, str(b["seq_idx"].dtype))
        check("labels 有 -100 分隔", bool((b["labels"] == -100).any()), "占用 %d 个位置"
              % int((b["labels"] == -100).sum()))
    else:
        check("现状产出 attention_mask 而非 cu_seq_lens", "attention_mask" in keys and "seq_idx" not in keys)

print("\n结果:", "全部 PASS" if not FAILS else "FAIL -> " + ", ".join(FAILS))
sys.exit(0 if not FAILS else 1)
