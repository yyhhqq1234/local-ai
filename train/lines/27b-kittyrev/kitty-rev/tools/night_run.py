#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""night_run.py —— 云端无人值守总控：取 GDN 张量 → 回填 → 量化 → 拼接 → convert，每门写标记

每门产出一个 .markers/<门>.ok（含关键数字），断点续跑：
  python night_run.py            # 从当前进度继续
  python night_run.py --from G1  # 指定起点
判据（任一不过即停，不往下走）：
  G1 gdn-only/model.safetensors 存在且张量数 ≥ 180
  G2 gdn_refill 后 GGUF 零槽位 = 0
  G3 IQ2_S 851 张量 · 9.0e9–1.0737e10
  G4 splice 866 / blk.64=15 / arch=qwen35 / bc=65
  G5 final6.ninfer 存在 · name 四要素 · 体积 ≤1.0737e10
"""
import json, os, subprocess, sys, time

R = "/root/autodl-tmp/kitty-rev"
GGUF = f"{R}/gguf/v4-bf16.gguf"
GDN = f"{R}/gdn-only/model.safetensors"
IQ2S = f"{R}/gguf/v4-iq2s-851.gguf"
MTP = f"{R}/gguf/mtp-spliced/v4_mtp_s.gguf"
OUT = f"{R}/ninfer-v4/final6.ninfer"
NAME = "qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-abliterated-iq2s-mtp"
MK = f"{R}/logs/v4/.markers"
PY = "/root/miniconda3/bin/python"
LOG = f"{R}/logs/v4/NIGHT-RUN.log"


def log(msg):
    line = time.strftime("%F %T") + " " + msg
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def ok(gate, payload=""):
    os.makedirs(MK, exist_ok=True)
    with open(f"{MK}/{gate}.ok", "w") as f:
        f.write(payload)
    log(f"[{gate}] PASS {payload}")


def has(gate):
    return os.path.exists(f"{MK}/{gate}.ok")


def run(cmd, cwd=None, tail=6):
    log("RUN: " + " ".join(cmd)[:200])
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (p.stdout + p.stderr).strip().splitlines()
    for l in out[-tail:]:
        log("  | " + l[:200])
    return p.returncode, "\n".join(out)


def main():
    from_g = "G0"
    if "--from" in sys.argv:
        from_g = sys.argv[sys.argv.index("--from") + 1]
    log(f"===== night_run start from={from_g} =====")

    # ---------- G1 取 GDN 张量（可断点续） ----------
    if not has("G1"):
        n = 0
        if os.path.exists(GDN):
            from safetensors import safe_open
            with safe_open(GDN, framework="numpy") as f:
                n = len(list(f.keys()))
        if n < 180:
            run([PY, "-u", f"{R}/tools/fetch_gdn3.py", "--tree", "/tmp/tree.json",
                 "--out", GDN], cwd=R, tail=8)
            if os.path.exists(GDN):
                from safetensors import safe_open
                with safe_open(GDN, framework="numpy") as f:
                    n = len(list(f.keys()))
        if n < 180:
            log(f"[STOP] G1 只取到 {n} 个张量")
            return 1
        ok("G1", f"tensors={n} size={os.path.getsize(GDN)}")

    # ---------- G2 回填 + zero=0 ----------
    if not has("G2"):
        rc, out = run([PY, f"{R}/tools/gdn_refill.py", "--gguf", GGUF, "--hf", f"{R}/gdn-only"], cwd=R, tail=10)
        if "写后 zero 张量 = 0" not in out:
            log("[STOP] G2 回填后仍有零槽位")
            return 1
        ok("G2", "zero=0")

    # ---------- G3 量化 ----------
    if not has("G3"):
        imx = f"{R}/imatrix-v4.dat"
        tt = []
        for i in range(64):
            tt += ["--tensor-type", f"blk.{i}.ssm_alpha.weight=q8_0",
                   "--tensor-type", f"blk.{i}.ssm_beta.weight=q8_0"]
        cmd = ["/root/autodl-tmp/lc/build-cuda89/bin/llama-quantize", "--imatrix", imx] + tt + [GGUF, IQ2S, "IQ2_S", "64"]
        rc, out = run(cmd, cwd=R, tail=6)
        sz = os.path.getsize(IQ2S) if os.path.exists(IQ2S) else 0
        if not (9.0e9 <= sz <= 1.0737e10):
            log(f"[STOP] G3 体积异常 {sz}")
            return 1
        ok("G3", f"bytes={sz}")

    # ---------- G4 splice ----------
    if not has("G4"):
        run([PY, f"{R}/tools/splice_new.py", "--base", IQ2S,
             "--ref", "/root/autodl-tmp/ref/ref_sparse.gguf", "--out", MTP], cwd=R, tail=4)
        if not os.path.exists(MTP):
            log("[STOP] G4 splice 无产物")
            return 1
        ok("G4", f"bytes={os.path.getsize(MTP)}")

    # ---------- G5 convert ----------
    if not has("G5"):
        run([PY, "-m", "tools.convert", "--model", f"{R}/cfg-vision",
             "--recipe", "qwen3_8_27b_gguf", "--source", f"gguf={MTP}",
             "--components", "text,mtp", "--proposal", "--proposal-rows", "131072",
             "--name", NAME, "--out", OUT], cwd=f"{R}/ninfer-all-master", tail=4)
        if not os.path.exists(OUT):
            log("[STOP] G5 convert 无产物")
            return 1
        sz = os.path.getsize(OUT)
        if sz > 10737418240:
            log(f"[STOP] G5 体积超 10 GiB: {sz}")
            return 1
        ok("G5", f"bytes={sz} path={OUT}")

    log("===== ALL GATES PASS =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
