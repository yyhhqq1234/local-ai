#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""p1_requant.py —— P1 诊断：同一份 gen3_1 权重在高精度档重量化（隔离"量化压能力" vs "没学会"）

与 local_finish_iq2s.py 的差别（只有三点，且是刻意的）：
  1) 预算从 9.40e9 → 10.60e9 字节（12G 卡上限；10.737e9 是本机既定天花板）
  2) 基础类型 IQ2_S → IQ3_S（抬高全体张量精度地板，单一变量）
  3) gguf 之后立刻删 merged（本机磁盘峰值：52G merged + 54G gguf + 10.7G 量化 = 需要中间释放）

判据：
  gate-merge   1199 张量
  gate-gguf    >= 50e9 字节
  gate-quant   9.0e9 <= size <= 10.85e9

用法：
  ./.venv/Scripts/python.exe scripts/p1_requant.py
  ./.venv/Scripts/python.exe scripts/p1_requant.py --stop-after gguf
  ./.venv/Scripts/python.exe scripts/p1_requant.py --stop-after quant --reuse
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# 路径统一走 _paths（2026-11-01 双线迁移后 train/lines/ 布局）
sys.path.insert(0, HERE)
from _paths import (TRAIN, LC_PY as LC, QUANT, SAFE_CONVERT, GGUF_PY,  # noqa: E402
                    BASE, LOCAL_PACK, MERGED, IMATRIX as IMX)
PY = sys.executable
MERGE = os.path.join(HERE, "local_merge_lora.py")
GSQ = os.path.join(HERE, "gsq_rco_plan.py")

ADAPTER = os.path.join(LOCAL_PACK, "gen3_1", "adapter-600")
WORK = os.path.join(MERGED, "gen3_1")
OUT = os.path.join(LOCAL_PACK, "gen3_1p")
GGUF = os.path.join(OUT, "gen3_1p-bf16.gguf")
PLAN = os.path.join(OUT, "gen3_1p-iq3s-types.txt")
COMPACT = os.path.join(OUT, "gen3_1p-iq3s-compact.txt")
RPT = os.path.join(OUT, "gen3_1p-iq3s-report.md")
QOUT = os.path.join(OUT, "gen3_1p-iq3s-gsqrco.gguf")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def run(cmd, env=None, timeout=None):
    log("RUN " + os.path.basename(cmd[0]) + " " + " ".join(cmd[1:4]) + " ...")
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, env=e, timeout=timeout)
    if p.returncode != 0:
        raise SystemExit(f"[FATAL] 退出码 {p.returncode}: {cmd[0]}")


def gate_merge(work):
    idx = os.path.join(work, "model.safetensors.index.json")
    if not os.path.isfile(idx):
        raise SystemExit(f"[gate-merge] FAIL 缺 {idx}")
    d = json.load(open(idx, encoding="utf-8"))
    nt = len(d["weight_map"])
    log(f"[gate-merge] 张量 {nt}")
    if nt < 1199:
        raise SystemExit(f"[gate-merge] FAIL 张量数 {nt} < 1199")
    log("[gate-merge] PASS")


def gate_gguf(p):
    sz = os.path.getsize(p)
    log(f"[gate-gguf] {sz/1e9:.2f} GB")
    if sz < 50e9:
        raise SystemExit("[gate-gguf] FAIL 体积 < 50GB")
    log("[gate-gguf] PASS")


def gate_quant(p, hi=10.85e9):
    sz = os.path.getsize(p)
    log(f"[gate-quant] {sz/1e9:.3f} GB（上限 {hi/1e9:.2f}）")
    if not (9.0e9 <= sz <= hi):
        raise SystemExit(f"[gate-quant] FAIL {sz} 不在 9.0e9~{hi}")
    log("[gate-quant] PASS")


def free_gb():
    t = shutil.disk_usage(TRAIN)
    return t.free / 1e9


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=10.60e9)
    ap.add_argument("--base-type", default="IQ3_S")
    ap.add_argument("--out", default="", help="输出目录（默认 local-pack/gen3_1p）")
    ap.add_argument("--gguf-in", default="", help="复用已有 bf16 gguf（跳过 merge/convert）")
    ap.add_argument("--gate-max", type=float, default=10.85e9, help="产物字节上限")
    ap.add_argument("--stop-after", default="quant", choices=["merge", "gguf", "quant"])
    ap.add_argument("--reuse", action="store_true", help="不重做 merge/gguf，只走后续")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 8)
    a = ap.parse_args()

    for p, n in ((LC, "convert_hf_to_gguf.py"), (QUANT, "llama-quantize.exe"),
                 (MERGE, "local_merge_lora.py"), (SAFE_CONVERT, "convert_gguf_safe.py"),
                 (GSQ, "gsq_rco_plan.py"), (IMX, "imatrix-gen2.dat"),
                 (BASE, "base/Qwen3.8-27B"), (ADAPTER, "adapter-600")):
        if not os.path.exists(p):
            raise SystemExit(f"[FATAL] 缺 {n}: {p}")

    # 输出目录/产物名按目录 basename 派生，支持多档并行（A/B 对比臂互不覆盖）
    global OUT, GGUF, PLAN, COMPACT, RPT, QOUT
    if a.out:
        OUT = os.path.abspath(a.out)
    tag = os.path.basename(OUT.rstrip("\\/"))
    PLAN = os.path.join(OUT, tag + "-types.txt")
    COMPACT = os.path.join(OUT, tag + "-compact.txt")
    RPT = os.path.join(OUT, tag + "-report.md")
    QOUT = os.path.join(OUT, tag + "-" + a.base_type.lower() + ".gguf")
    if a.gguf_in:
        GGUF = os.path.abspath(a.gguf_in)
    else:
        GGUF = os.path.join(OUT, tag + "-bf16.gguf")
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    log(f"空闲磁盘 {free_gb():.1f} GB | budget={a.budget/1e9:.2f}e9 base-type={a.base_type}")

    # 1) merge
    idx = os.path.join(WORK, "model.safetensors.index.json")
    gguf_ready = os.path.isfile(GGUF) and os.path.getsize(GGUF) > 50e9
    if a.reuse and gguf_ready:
        # gguf 已是完整源，merged 只是中间体（可能已被上一轮删除或只写了一半）
        if os.path.isdir(WORK):
            log(f"gguf 已就绪，清理残留 merged {WORK}")
            shutil.rmtree(WORK, ignore_errors=True)
        log(f"跳过 merge/gguf（bf16 gguf 已存在 {os.path.getsize(GGUF)/1e9:.1f} GB）")
    else:
        if os.path.isfile(idx) and a.reuse:
            log(f"merge 复用 {WORK}")
        else:
            if os.path.isdir(WORK):
                log(f"清空半成品 {WORK}")
                shutil.rmtree(WORK, ignore_errors=True)
            need = 60.0
            if free_gb() < need:
                raise SystemExit(f"[FATAL] 空闲 {free_gb():.1f} GB < merge 需求 {need} GB")
            run([PY, "-X", "utf8", MERGE, "--base", BASE, "--adapter", ADAPTER, "--out", WORK])
        gate_merge(WORK)
        if a.stop_after == "merge":
            log(f"[STOP] merge 完成 {(time.time()-t0)/60:.1f}min 空闲 {free_gb():.1f} GB")
            return 0

        # 2) bf16 gguf
        if os.path.isfile(GGUF) and os.path.getsize(GGUF) > 50e9:
            log(f"gguf 复用 {GGUF}")
        else:
            if free_gb() < 56.0:
                raise SystemExit(f"[FATAL] 空闲 {free_gb():.1f} GB < gguf 需求 56 GB")
            run([PY, "-X", "utf8", SAFE_CONVERT, WORK, "--outfile", GGUF, "--outtype", "bf16"],
                env={"CONVERT_PY": LC, "PYTHONPATH": GGUF_PY})
        gate_gguf(GGUF)
        if a.stop_after == "gguf":
            log(f"[STOP] gguf 完成 {(time.time()-t0)/60:.1f}min 空闲 {free_gb():.1f} GB")
            return 0

        # 3) 释放 merged（gguf 已是完整源，merged 可重建）
        if os.path.isdir(WORK):
            log(f"删除 merged {WORK}（释放磁盘，gguf 为源）")
            shutil.rmtree(WORK, ignore_errors=True)
    log(f"进入量化阶段，空闲 {free_gb():.1f} GB")

    # 4) GSQ-RCO 配方
    if not os.path.isfile(PLAN):
        run([PY, "-X", "utf8", GSQ, "--gguf", GGUF, "--imatrix", IMX,
             "--budget", f"{a.budget:.0f}", "--base-type", a.base_type,
             "--out", PLAN, "--report", RPT])
    tt = []
    for line in open(PLAN, encoding="utf-8"):
        line = line.strip()
        if line.startswith("--tensor-type "):
            line = line[len("--tensor-type "):].strip()
        if not line:
            continue
        k, v = line.rsplit("=", 1)
        tt += ["--tensor-type", k + "=" + v]
    log(f"GSQ-RCO 配方 {len(tt)//2} 条 → {PLAN}")

    # Windows CreateProcess 命令行上限 32767 字符：逐张量表会直接 WinError 206，
    # 先压成按层类正则（compact_tt.py 会做逐张量等价校验，不一致即非 0 退出）
    argv_len = sum(len(x) + 3 for x in tt) + len(GGUF) + len(QOUT) + len(a.base_type) + 200
    if argv_len > 30000:
        log(f"命令行估算 {argv_len} 字符 > 30000，启用层类归并")
        run([PY, "-X", "utf8", os.path.join(HERE, "compact_tt.py"),
             "--gguf", GGUF, "--plan", PLAN, "--out", COMPACT])
        tt = []
        for line in open(COMPACT, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            k, v = line.rsplit("=", 1)
            tt += ["--tensor-type", k + "=" + v]
        argv_len = sum(len(x) + 3 for x in tt) + len(GGUF) + len(QOUT) + len(a.base_type) + 200
        log(f"归并后 {len(tt)//2} 条，命令行估算 {argv_len} 字符")
        if argv_len > 32000:
            raise SystemExit(f"[FATAL] 归并后仍超限 {argv_len}")

    # 5) 量化
    if os.path.isfile(QOUT):
        log(f"量化产物已存在 {QOUT}")
    else:
        run([QUANT, "--imatrix", IMX] + tt + [GGUF, QOUT, a.base_type, str(a.threads)],
            timeout=3600 * 6)
    gate_quant(QOUT, a.gate_max)

    log(f"[DONE] P1 量化完成 {(time.time()-t0)/60:.1f}min 空闲 {free_gb():.1f} GB")
    log(f"  产物 {QOUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
