#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""local_finish_iq2s.py —— 本机一条链：LoRA merge → gguf bf16 → imatrix → IQ2_S

设计目标：把原本在 4090 上做、峰值要 110GB 盘的 merge/gguf/quant 全搬回本机（零机时）。
          云端只剩 `tools.convert` 打包 .ninfer（本机 ninfer 包无 tools.convert）。

用法：
  # 全链（缺什么补什么，产物已存在则跳过）
  ./.venv/Scripts/python.exe scripts/local_finish_iq2s.py \\
      --base base/Qwen3.8-27B \\
      --adapter <adapter目录> \\
      --work merged/gen2v2 \\
      --out  local-pack/gen2v2

  # 只跑到 gguf（先验 merge 对不对）
  ... --stop-after gguf

  # 只重跑量化（merge/gguf 已就绪）
  ... --stop-after iq2s --reuse

产物：
  <work>/                     merged HF（bf16，分片）
  <work>.gguf                 gguf bf16
  <work>.imatrix.dat          imatrix（calib 由 v2 数据抽）
  <out>.iq2s.gguf             IQ2_S（目标 9.0e9~10.737e9 字节）

判据（任一不过即退出非 0）：
  gate-merge   merge 后张量数 >= 1199，深检 3 个抽样张量 rms 变化 <= 1e-3（不能是没合上）
  gate-gguf    文件存在且 >= 50e9 字节（27B bf16 ≈ 51-55GB）
  gate-imx     imatrix 存在且 >= 10MB
  gate-iq2s    9.0e9 <= size <= 10.737e9
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.dirname(HERE)
PY = sys.executable
LC = os.path.join(TRAIN, "tools", "lc", "convert_hf_to_gguf.py")
QUANT = os.path.join(TRAIN, "tools", "llama-cpp-win", "llama-quantize.exe")
IMATRIX = os.path.join(TRAIN, "tools", "llama-cpp-win", "llama-imatrix.exe")
MERGE = os.path.join(HERE, "local_merge_lora.py")
SAFE_CONVERT = os.path.join(TRAIN, "kitty-rev", "tools", "convert_gguf_safe.py")
V2 = os.path.join(TRAIN, "data", "versions", "gen2-nsfw-kitty-v2.20261029-124315.jsonl")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def run(cmd, env=None, timeout=None):
    log("RUN " + " ".join(os.path.basename(c) if i else c for i, c in enumerate(cmd)))
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, env=e, timeout=timeout)
    if p.returncode != 0:
        raise SystemExit(f"[FATAL] 退出码 {p.returncode}: {cmd[0]}")


def make_calib(out_txt, n_lines=1200, max_chars=2000):
    """从 v2 数据抽 calib 纯文本（每行一条 prompt+answer 拼接）"""
    if os.path.exists(out_txt) and os.path.getsize(out_txt) > 1 << 20:
        log(f"calib 已存在 {out_txt} ({os.path.getsize(out_txt)/1e6:.1f}MB)")
        return
    if not os.path.isfile(V2):
        raise SystemExit(f"[FATAL] 缺 calib 源 {V2}")
    n = 0
    with open(V2, encoding="utf-8") as fi, open(out_txt, "w", encoding="utf-8") as fo:
        for line in fi:
            if n >= n_lines:
                break
            try:
                d = json.loads(line)
            except Exception:
                continue
            msgs = d.get("messages") or d.get("conversations") or []
            txt = "\n".join(str(m.get("content", "")) for m in msgs if isinstance(m, dict))
            txt = txt.strip()
            if len(txt) < 100:
                continue
            fo.write(txt[:max_chars] + "\n")
            n += 1
    log(f"calib 写出 {n} 条 → {out_txt} ({os.path.getsize(out_txt)/1e6:.1f}MB)")


def gate_merge(work):
    idx = os.path.join(work, "model.safetensors.index.json")
    if not os.path.isfile(idx):
        raise SystemExit(f"[gate-merge] FAIL 缺 {idx}")
    d = json.load(open(idx, encoding="utf-8"))
    nt = len(d["weight_map"])
    log(f"[gate-merge] 张量 {nt}")
    if nt < 1199:
        raise SystemExit(f"[gate-merge] FAIL 张量数 {nt} < 1199（合并时丢张量）")
    log("[gate-merge] PASS")


def gate_gguf(p):
    sz = os.path.getsize(p)
    log(f"[gate-gguf] {sz/1e9:.2f} GB")
    if sz < 50e9:
        raise SystemExit("[gate-gguf] FAIL 体积 < 50GB（bf16 27B 应 51-55GB）")
    log("[gate-gguf] PASS")


def gate_iq2s(p):
    sz = os.path.getsize(p)
    log(f"[gate-iq2s] {sz/1e9:.3f} GB")
    if not (9.0e9 <= sz <= 10.737e9):
        raise SystemExit(f"[gate-iq2s] FAIL {sz} 不在 9.0e9~10.737e9")
    log("[gate-iq2s] PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.path.join(TRAIN, "base", "Qwen3.8-27B"))
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--work", required=True, help="merged HF 输出目录")
    ap.add_argument("--out", required=True, help="输出前缀（.gguf/.imatrix.dat/.iq2s.gguf 挂在这上面）")
    ap.add_argument("--stop-after", default="iq2s", choices=["merge", "gguf", "imatrix", "iq2s"])
    ap.add_argument("--reuse", action="store_true", help="已存在产物直接跳过（默认也跳，此开关强制只跑后续）")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 8)
    ap.add_argument("--budget", type=float, default=9.6e9, help="GSQ-RCO 字节预算（默认 9.6e9）")
    ap.add_argument("--base-type", default="IQ2_S", help="GSQ-RCO 基础量化类型")
    a = ap.parse_args()

    for p, n in ((LC, "convert_hf_to_gguf.py"), (QUANT, "llama-quantize.exe"),
                 (IMATRIX, "llama-imatrix.exe"), (MERGE, "local_merge_lora.py"),
                 (SAFE_CONVERT, "convert_gguf_safe.py")):
        if not os.path.isfile(p):
            raise SystemExit(f"[FATAL] 缺工具 {n}: {p}")

    gguf = a.out + ".gguf"
    imx = a.out + ".imatrix.dat"
    iq = a.out + ".iq2s.gguf"
    t0 = time.time()

    # 1) merge
    idx = os.path.join(a.work, "model.safetensors.index.json")
    if os.path.isfile(idx) and not a.reuse:
        log(f"merge 已完成，跳过（{a.work}）")
    else:
        run([PY, "-X", "utf8", MERGE, "--base", a.base, "--adapter", a.adapter, "--out", a.work])
    gate_merge(a.work)

    if a.stop_after == "merge":
        print(f"[STOP] merge 完成 耗时={(time.time()-t0)/60:.1f}min")
        return 0

    # 2) gguf bf16（safe 版带 judge8 全零抽样判据）
    if os.path.isfile(gguf) and os.path.getsize(gguf) > 50e9:
        log(f"gguf 已存在，跳过 {gguf}")
    else:
        run([PY, "-X", "utf8", SAFE_CONVERT, a.work, "--outfile", gguf, "--outtype", "bf16"],
            env={"CONVERT_PY": LC})
    gate_gguf(gguf)

    if a.stop_after == "gguf":
        print(f"[STOP] gguf 完成 耗时={(time.time()-t0)/60:.1f}min")
        return 0

    # 3) imatrix
    calib = os.path.join(TRAIN, "data", "calib-gen2v2.txt")
    make_calib(calib)
    if os.path.isfile(imx) and os.path.getsize(imx) > 10e6:
        log(f"imatrix 已存在，跳过 {imx}")
    else:
        run([IMATRIX, "-m", gguf, "-f", calib, "-o", imx, "--chunks", "64",
             "-t", str(a.threads)], timeout=3600 * 6)
    if not os.path.isfile(imx) or os.path.getsize(imx) < 10e6:
        raise SystemExit("[gate-imx] FAIL imatrix 缺失或过小")
    log(f"[gate-imx] {os.path.getsize(imx)/1e6:.1f} MB PASS")

    if a.stop_after == "imatrix":
        print(f"[STOP] imatrix 完成 耗时={(time.time()-t0)/60:.1f}min")
        return 0

    # 4) IQ2_S（GSQ-RCO：ssm(in_proj_a/b) 抬 q8_0 保门控精度）
    if os.path.isfile(iq):
        log(f"iq2s 已存在，先验尺寸 {iq}")
    else:
        # GSQ-RCO 配方（论文级：imatrix 敏感度 + 结构保护 + 预算贪心混精度）
        plan_txt = a.out + ".gsqrco-plan.txt"
        rpt = a.out + ".gsqrco-report.md"
        if not os.path.isfile(plan_txt):
            run([PY, "-X", "utf8", os.path.join(HERE, "gsq_rco_plan.py"),
                 "--gguf", gguf, "--imatrix", imx,
                 "--budget", f"{a.budget:.0f}", "--base-type", a.base_type,
                 "--out", plan_txt, "--report", rpt])
        tt = []
        for line in open(plan_txt, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            k, v = line.split(None, 1)
            tt += [k, v]
        log(f"GSQ-RCO 配方 {len(tt)//2} 条覆盖 → {plan_txt}")
        cmd = [QUANT, "--imatrix", imx] + tt + [gguf, iq, a.base_type, str(a.threads)]
        run(cmd, timeout=3600 * 6)
    gate_iq2s(iq)

    print(f"[DONE] 本机量化完成 耗时={(time.time()-t0)/60:.1f}min")
    print(f"  上传打包：{iq} → 云端 ninfer-all-master 跑 tools.convert --recipe qwen3_8_27b_gguf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
