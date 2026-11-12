#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""preflight_gen4.py — 花钱前的 12 道自检（任一 FAIL 就别开训）

把这一轮踩过的坑全部前置成断言，避免「跑完 3.5 小时才发现数据/脚本/config 有问题」：

  P1 数据集存在 + sha 与训练脚本 EXPECT_SHA 一致
  P2 全量 chat template 渲染 0 失败、0 超 ctx
  P3 tool_calls 行占比 ≥ 8%（修 A1 的硬指标）
  P4 门控 pos:neg ∈ [1.5, 3.0] 且正样本开头无编排词
  P5 结构化 tool_calls 的 arguments 全是 mapping（Qwen template 强制）
  P6 训练脚本的 DATA/INIT/OUT/EXPECT_SHA 四项与本地一致
  P7 量化依赖在位：imatrix / plan-final2 / llama-quantize / ninfer recipe / mmproj
  P8 看门狗 POWER 路径存在（C11：少一级 /deploy/ 会空烧钱）
  P9 门控脚本带 reasoning_effort（C13：不发 effort 会得到假 recall）
  P10 长文探针带空回复重试（C14 同源坑）
  P11 磁盘 ≥ 60 GB、显存无僵尸进程占用
  P12 云端实例状态（能连就查，连不上记 SKIP）

用法：python preflight_gen4.py [--data ...] [--script ...] [--cloud]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

W = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", ".."))  # scripts → _shared → lines → train → 仓库根
V = os.path.join(W, "train", "lines", "27b-kittyrev", "data", "versions")
DEFAULT_DATA = os.path.join(V, "gen4-nsfw-kitty.jsonl")
DEFAULT_SCRIPT = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev",
                              "deploy", "cloud", "gen4_5090.sh")
BASE_TOK = os.path.join(W, "train", "lines", "27b-kittyrev", "base", "Qwen3.8-27B")

ORCH = ("识别到", "先判断", "落点", "拆解", "可执行", "可交付", "同步进度", "常规模式")

res = []


def check(pid, name, ok, detail=""):
    res.append((pid, name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {pid} {name}" + (f" — {detail}" if detail else ""))
    return ok


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:16]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--script", default=DEFAULT_SCRIPT)
    ap.add_argument("--cloud", action="store_true")
    a = ap.parse_args()

    # P1 存在 + sha
    if not check("P1a", "数据集存在", os.path.isfile(a.data), a.data):
        print("\n[STOP] 数据都没有，后面的检查无意义")
        return 1
    sc = open(a.script, encoding="utf-8").read() if os.path.isfile(a.script) else ""
    m = re.search(r"EXPECT_SHA=([0-9a-f]{8,64})", sc)
    exp = m.group(1) if m else ""
    # 训练真正吃的是脚本里 DATA 指向的文件（通常是预渲染的 *-text.jsonl）
    m_d = re.search(r"DATA=\$\{DATA:-[^}]*/([^/}]+)\}", sc)
    train_name = m_d.group(1) if m_d else os.path.basename(a.data)
    cand = [os.path.join(os.path.dirname(a.data), train_name), a.data]
    cmp_path = next((c for c in cand if os.path.isfile(c)), a.data)
    got = sha16(cmp_path)
    check("P1b", "训练脚本 DATA 的 sha 与 EXPECT_SHA 一致",
          got.startswith(exp) and bool(exp),
          f"{os.path.basename(cmp_path)} {got} / 脚本 {exp or '缺失'}")

    # P2/P3/P4/P5 一次遍历
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(BASE_TOK, trust_remote_code=True)
        tok_ok = True
    except Exception as e:  # noqa: BLE001
        tok_ok = False
        print(f"[warn] tokenizer 不可用（{e}），P2 跳过")
        tok = None

    n = 0
    bad_render = over = tc_rows = tools_rows = arg_bad = 0
    pos = neg = pos_orch = 0
    lens = []
    for line in open(a.data, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        n += 1
        msgs = r.get("messages") or []
        if r.get("tools"):
            tools_rows += 1
        has_tc = False
        for mm in msgs:
            for tc in (mm.get("tool_calls") or []):
                has_tc = True
                arg = (tc.get("function") or {}).get("arguments")
                if not isinstance(arg, dict):
                    arg_bad += 1
        if has_tc:
            tc_rows += 1
        s = "".join(mm.get("content") or "" for mm in msgs if mm.get("role") == "system")
        if s.startswith("模式："):
            ans = "".join(x.get("content") or "" for x in msgs if x.get("role") == "assistant")
            if "NSFW" in s:
                pos += 1
                if any(w in ans[:200] for w in ORCH):
                    pos_orch += 1
            else:
                neg += 1
        if tok is not None:
            try:
                txt = (tok.apply_chat_template(msgs, tools=r["tools"], tokenize=False,
                                               add_generation_prompt=False)
                       if r.get("tools") else
                       tok.apply_chat_template(msgs, tokenize=False,
                                               add_generation_prompt=False))
                ln = len(tok(txt, add_special_tokens=False)["input_ids"])
                lens.append(ln)
                if ln > 2048:
                    over += 1
            except Exception:  # noqa: BLE001
                bad_render += 1

    check("P2", "渲染 0 失败 / 0 超 ctx",
          bad_render == 0 and over == 0,
          f"行 {n}，渲染失败 {bad_render}，超 2048 {over}，"
          f"max {max(lens) if lens else '-'}")
    check("P3", "tool_calls 行占比 ≥ 8%",
          tc_rows / max(1, n) >= 0.08,
          f"{tc_rows}/{n} = {tc_rows/max(1,n)*100:.2f}%；tools 非空 {tools_rows}")
    ratio = pos / max(1, neg)
    check("P4", "门控 pos:neg ∈ [1.5,3] 且正样本无编排词",
          1.5 <= ratio <= 3.0 and pos_orch == 0,
          f"pos {pos} : neg {neg} = {ratio:.2f}:1；含编排词 {pos_orch}")
    check("P5", "tool_calls.arguments 全为 mapping", arg_bad == 0, f"非 mapping {arg_bad}")

    # P6 训练脚本四要素
    keys = ("DATA=", "INIT=", "OUT=", "EXPECT_SHA=")
    miss = [k for k in keys if k not in sc]
    m_d = re.search(r"DATA=\$\{DATA:-\$KDIR/data/gen2/([^}]+)\}", sc) or \
          re.search(r"DATA=\$\{DATA:-[^}]*/([^/}]+)\}", sc)
    data_name = m_d.group(1) if m_d else "?"
    check("P6", "训练脚本 DATA/INIT/OUT/EXPECT_SHA 就位",
          not miss and data_name != "?",
          f"DATA={data_name}" + ("" if not miss else f" 缺 {miss}"))

    # P7 量化依赖
    deps = {
        "imatrix": os.path.join(W, "train", "lines", "27b-kittyrev", "quant", "imatrix-gen2.dat"),
        "plan-final2": os.path.join(W, "train", "lines", "27b-kittyrev", "local-pack",
                                    "errsweep", "plan-final2.txt"),
        "llama-quantize": os.path.join(W, "train", "lines", "_shared", "tools",
                                       "llama-cpp-win", "llama-quantize.exe"),
        "ninfer recipe": os.path.join(W, "train", "lines", "_shared", "tools",
                                      "ninfer-all-master", "tools", "convert", "gguf_blocks.py"),
        "mmproj": os.path.join(W, "train", "lines", "27b-kittyrev", "local-pack",
                               "gen3", "gen3-mmproj.gguf"),
        "merge_stream": os.path.join(W, "train", "lines", "_shared", "scripts",
                                     "merge_stream_27b.py"),
    }
    bad = [k for k, p in deps.items() if not os.path.exists(p)]
    check("P7", "量化/合并依赖在位", not bad, f"缺 {bad}" if bad else "6/6 在位")

    # P8 看门狗 POWER 路径
    wd = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy", "cloud",
                      "gen3_1p_watchdog.py")
    power = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy",
                         "autodl_power.py")
    wdt = open(wd, encoding="utf-8").read() if os.path.isfile(wd) else ""
    ref = re.search(r'POWER\s*=\s*os\.path\.join\(([^\n]+)\)', wdt)
    ok8 = bool(ref) and "dirname(HERE)" in ref.group(1) and "dirname(os.path.dirname(HERE))" not in ref.group(1)
    check("P8", "看门狗 POWER 指向 deploy/autodl_power.py",
          ok8 and os.path.isfile(power), f"POWER 表达式 {ref.group(1).strip()[:60] if ref else '未找到'}")

    # P9 门控脚本带 effort
    g = os.path.join(W, "train", "lines", "_shared", "scripts", "nsfw_gate_eval.py")
    gt = open(g, encoding="utf-8").read() if os.path.isfile(g) else ""
    check("P9", "门控脚本发送 reasoning_effort",
          '"reasoning_effort"' in gt and "--effort" in gt, "含 reasoning_effort + --effort")

    # P10 长文探针带重试
    lp = os.path.join(W, "train", "lines", "_shared", "scripts", "longtext_probe.py")
    lt = open(lp, encoding="utf-8").read() if os.path.isfile(lp) else ""
    check("P10", "长文探针带空回复重试", "[retry]" in lt and "range(3)" in lt,
          "含 [retry] 与 3 次重试")

    # P11 磁盘 / 显存
    du = shutil.disk_usage("D:\\")
    free_gb = du.free / (1 << 30)
    vram = "n/a"
    zombie = 0
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name",
                              "--format=csv,noheader"], capture_output=True, text=True,
                             errors="ignore").stdout.strip()
        zombie = len([x for x in out.splitlines() if x.strip()])
        vram = out or "无占用"
    except Exception:  # noqa: BLE001
        pass
    check("P11", "磁盘 ≥ 60 GB 且无僵尸显存进程",
          free_gb >= 60 and zombie == 0, f"空闲 {free_gb:.0f} GB；GPU 进程 {zombie}")

    # P12 云端状态
    if a.cloud:
        pyp = r"C:\ProgramData\anaconda3\python.exe"
        pwr = os.path.join(W, "train", "lines", "27b-kittyrev", "kitty-rev", "deploy",
                           "autodl_power.py")
        try:
            r = subprocess.run([pyp, "-X", "utf8", pwr, "status"], capture_output=True,
                               text=True, errors="ignore", timeout=60)
            st = "unknown"
            try:
                st = json.loads(r.stdout[r.stdout.index("{"):]).get("status", "unknown")
            except Exception:  # noqa: BLE001
                st = (r.stdout or r.stderr)[:60]
            check("P12", "云端实例状态可读", True, st)
        except Exception as e:  # noqa: BLE001
            check("P12", "云端实例状态可读", False, str(e)[:60])
    else:
        print("[SKIP] P12 云端实例状态（未加 --cloud）")

    fails = [x for x in res if not x[2]]
    print("\n" + "=" * 60)
    print(f"预检结果：{len(res)-len(fails)}/{len(res)} PASS"
          + ("" if not fails else f"   ❌ FAIL: {[x[0] for x in fails]}"))
    print("=" * 60)
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(main())
