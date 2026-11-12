#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RE adapter 能力验证 —— 训练前后对比工具调用是否正确

验证目标：
  1. adapter 能否正常加载
  2. 对 kitty 风格的逆向任务，是否输出正确的工具名 + 参数格式
  3. 与基座对比，确认学到了工具编排范式（而非只是复读）

判定口径：
  · 工具名命中：输出中出现 kitty_* 里的正确工具名
  · 参数完整：出现 action= 或 JSON 参数结构
  · 格式合规：不出现编造的工具名（如 kitty_xxx 不存在）

用法：
  # 只测 adapter
  python eval_re_adapter.py --adapter train/lines/9b-oxcoder/out/re-stage1-fixed/final
  # 基座 vs adapter 对比
  python eval_re_adapter.py --adapter train/lines/9b-oxcoder/out/re-stage1-fixed/final --compare-base
"""

import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

import torch

BASE = "train/lines/9b-oxcoder/models/OxCoder-9B"
GIB = 2 ** 30

# kitty 真实工具名（判定"编造工具"用）
KITTY_TOOLS = [
    "kitty_ce", "kitty_patch", "kitty_sym", "kitty_asm", "kitty_pwndbg",
    "kitty_dump", "kitty_inject", "kitty_prot", "kitty_drv", "kitty_init",
    "kitty_status", "kitty_selfcheck", "kitty_ops", "kitty_km", "kitty_x64dbg",
    "kitty_ida", "kitty_ghidra", "kitty_frida", "kitty_apk", "kitty_jadx",
    "kitty_die", "kitty_assetrip", "kitty_unpack", "kitty_il2cppdumper",
    "kitty_bepinex", "kitty_ue4ss", "kitty_uedump", "kitty_dnspy",
]

# 5 个测试场景（逆向工作台典型任务）
CASES = [
    {
        "name": "符号查询",
        "system": "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。工具的 action 取值见各自 schema 的 enum；不要先查工具清单表，按任务直接选工具并给全参数。",
        "user": "要看内存里已加载模块的导入表",
        "expect_tool": ["kitty_sym"],
        "expect_kw": ["imports"],
    },
    {
        "name": "静态补丁",
        "system": "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。",
        "user": "把这个 exe 里 0x1234 处的 74 0A 改成 EB 0A",
        "expect_tool": ["kitty_patch"],
        "expect_kw": ["patch"],
    },
    {
        "name": "内存读取",
        "system": "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。",
        "user": "读一下 0x7FF6DADB1000 处的 dword 值",
        "expect_tool": ["kitty_ce"],
        "expect_kw": ["R", "dword"],
    },
    {
        "name": "指针链反查",
        "system": "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。",
        "user": "帮我反查 0x7FF75FCD1000 这个地址的指针链，扫 0x7FF700000000 到 0x7FFF00000000",
        "expect_tool": ["kitty_pchain", "kitty_ce"],
        "expect_kw": ["P_BACK", "P_WALK", "target"],
    },
    {
        "name": "加壳识别",
        "system": "你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。",
        "user": "这个 dll 是不是被 UPX 加壳了？",
        "expect_tool": ["kitty_die", "kitty_unpack"],
        "expect_kw": ["detect", "packer", "UPX"],
    },
]


def load_model(adapter=None):
    from transformers import AutoModelForImageTextToText as AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModelForCausalLM.from_pretrained(
        BASE, device_map={"": 0}, low_cpu_mem_usage=True,
        attn_implementation="sdpa", quantization_config=bnb,
    )
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)
        print("[load] adapter 已挂载: %s" % adapter)
    # 大表与全量参数转 bf16（与训练一致）
    for p in model.parameters():
        if p.dtype == torch.float32:
            p.data = p.data.to(torch.bfloat16)
    model.eval()
    # 卸载视觉塔
    inner = getattr(model, "model", None)
    if inner is not None and getattr(inner, "visual", None) is not None:
        inner.visual = None
        torch.cuda.empty_cache()
    print("[load] allocated = %.2f GiB" % (torch.cuda.memory_allocated() / GIB))
    return model, tok


@torch.no_grad()
def gen(model, tok, system, user, max_new=220):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    text = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
    ids = tok(text, return_tensors="pt", add_special_tokens=False).to(model.device)
    out = model.generate(
        **ids, max_new_tokens=max_new, do_sample=False,
        temperature=None, top_p=None, pad_token_id=tok.eos_token_id,
    )
    new = out[0][ids["input_ids"].shape[1]:]
    return tok.decode(new, skip_special_tokens=True).strip()


def score(resp, case):
    """三个维度打分"""
    tool_hit = any(t in resp for t in case["expect_tool"])
    kw_hits = sum(1 for k in case["expect_kw"] if k.lower() in resp.lower())
    kw_ok = kw_hits >= max(1, len(case["expect_kw"]) // 2)
    # 编造工具检测：出现 kitty_ 但不在白名单
    import re

    found = set(re.findall(r"kitty_[a-z0-9_]+", resp))
    fake = found - set(KITTY_TOOLS)
    return {
        "tool_hit": tool_hit,
        "kw_ok": kw_ok,
        "kw_hits": kw_hits,
        "fake_tools": sorted(fake),
        "pass": tool_hit and kw_ok and not fake,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--compare-base", dest="cmp", action="store_true")
    ap.add_argument("--max-new", type=int, default=220)
    args = ap.parse_args()

    print("=" * 78)
    print("RE adapter 能力验证")
    print("=" * 78)

    model, tok = load_model(args.adapter)

    total_pass = 0
    for i, c in enumerate(CASES, 1):
        print()
        print("-" * 78)
        print("[%d/5] %s" % (i, c["name"]))
        print("  Q: %s" % c["user"])
        resp = gen(model, tok, c["system"], c["user"], args.max_new)
        s = score(resp, c)
        print("  A(前 260 字): %s" % resp[:260].replace("\n", "⏎"))
        print("  判定: 工具命中=%s 关键词=%d/%d 编造工具=%s → %s"
              % (s["tool_hit"], s["kw_hits"], len(c["expect_kw"]),
                 s["fake_tools"] or "无", "✅ PASS" if s["pass"] else "❌ FAIL"))
        total_pass += 1 if s["pass"] else 0

    print()
    print("=" * 78)
    print("结果：%d/5 PASS" % total_pass)
    print("=" * 78)

    if args.cmp:
        print()
        print("切换到基座（无 adapter）对比...")
        del model
        torch.cuda.empty_cache()
        base_model, _ = load_model(None)
        base_pass = 0
        for i, c in enumerate(CASES, 1):
            resp = gen(base_model, tok, c["system"], c["user"], args.max_new)
            s = score(resp, c)
            print("  [%d] %-10s → %s (工具=%s 关键词=%d/%d)"
                  % (i, c["name"], "PASS" if s["pass"] else "FAIL",
                     s["tool_hit"], s["kw_hits"], len(c["expect_kw"])))
            base_pass += 1 if s["pass"] else 0
        print()
        print("对比：adapter %d/5  vs  基座 %d/5" % (total_pass, base_pass))
        print("→ %s" % ("✅ adapter 有提升" if total_pass > base_pass
                        else "⚠ 无提升，需检查 adapter 是否生效" if total_pass == base_pass
                        else "❌ adapter 反而变差"))


if __name__ == "__main__":
    main()
