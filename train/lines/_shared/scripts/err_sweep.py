#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""err_sweep.py —— 实测「每张量 × 每类型」的重构误差，给分配器提供真数（GSQ 目标函数的可执行版）

背景：GSQ（arXiv 2604.18556）把量化写成
        ŵ = argmin ||f(x;ŵ) − f(x;w)||²
      我们无法在 NInfer 里学网格（引擎只认 iq*/k-quant，且无源码加格式），
      但可以用现成编码器把这个目标函数当分配判据：
      逐张量实测每个候选类型的加权重构误差，再在字节预算下求解最优分配。

加权口径（GSQ 式 (1) 的对角近似）：
      L_t = Σ_j E[x_j²]·(ŵ[:,j] − w[:,j])²      E[x_j²] 来自 imatrix 每通道向量

工程要点：
  不 memmap 全量 gguf（31.5 GB 机器 + OxCoder 同跑会 OOM，实测撞过
  "Unable to allocate 1.06 MiB"）→ 全部按 data_offset 直读所需行。
  张量按行采样（块对齐），采样行数 --rows 默认 64。

用法：
  python err_sweep.py --bf16 <bf16.gguf> --imatrix <imx.dat> --out stats.jsonl \
      --types IQ2_S,Q2_K,IQ3_S,IQ4_XS --rows 64
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# 路径统一走 _paths（2026-11-01 双线迁移后 train/lines/ 布局）
sys.path.insert(0, HERE)
from _paths import TRAIN, QUANT, GGUF_PY  # noqa: E402
sys.path.insert(0, GGUF_PY)

import numpy as np  # noqa: E402
import gguf  # noqa: E402
from gguf.quants import dequantize  # noqa: E402


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def read_imatrix_channels(path):
    """imatrix → {tensor: float32[nval]}（每通道 E[x²]），裸二进制流格式"""
    buf = open(path, "rb").read()
    pat = re.compile(rb"^[A-Za-z0-9_.]+\.(weight|bias)$")
    out, pos, n = {}, 0, len(buf)
    while pos + 8 < n:
        ln = struct.unpack_from("<i", buf, pos)[0]
        if 3 <= ln <= 120 and pos + 4 + ln + 8 <= n:
            name = buf[pos + 4:pos + 4 + ln]
            if pat.match(name):
                q = pos + 4 + ln
                ncall, nval = struct.unpack_from("<ii", buf, q)
                if 0 <= nval <= 100000 and ncall >= 0 and q + 8 + 4 * nval <= n:
                    out[name.decode()] = np.frombuffer(
                        buf, dtype="<f4", count=nval, offset=q + 8).astype(np.float32)
                    pos = q + 8 + 4 * nval
                    continue
        pos += 1
    return out


def read_rows(fh, offset, nbytes_row, rows):
    fh.seek(offset)
    raw = fh.read(rows * nbytes_row)
    if len(raw) != rows * nbytes_row:
        raise ValueError(f"短读 {len(raw)} != {rows * nbytes_row}")
    return np.frombuffer(raw, dtype=np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bf16", required=True)
    ap.add_argument("--imatrix", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--types", default="IQ2_S,Q2_K,IQ3_S,IQ4_XS")
    ap.add_argument("--rows", type=int, default=64)
    ap.add_argument("--keep-arms", action="store_true")
    ap.add_argument("--threads", type=int, default=20)
    a = ap.parse_args()

    types = [t.strip() for t in a.types.split(",") if t.strip()]
    imx = read_imatrix_channels(a.imatrix)
    log(f"imatrix 通道 {len(imx)} 张量")

    ref = gguf.GGUFReader(a.bf16)
    meta = {}
    for t in ref.tensors:
        shape = tuple(int(x) for x in t.shape)
        if len(shape) != 2:
            continue
        bpr = t.n_bytes // shape[1]
        if bpr * shape[1] != t.n_bytes:
            continue
        meta[t.name] = (shape, bpr, int(t.data_offset), t.tensor_type)
    log(f"参考元信息 {len(meta)} 张量（按需读行，不 memmap 全量）")
    del ref

    outdir = os.path.join(os.path.dirname(os.path.abspath(a.out)), "arms")
    os.makedirs(outdir, exist_ok=True)
    fh = open(a.bf16, "rb")

    with open(a.out, "w", encoding="utf-8") as fo:
        for ty in types:
            arm = os.path.join(outdir, f"sweep-{ty}.gguf")
            # 残臂检查：上一轮量化失败可能留下 0 字节/截断文件，必须删掉重做
            if os.path.isfile(arm) and os.path.getsize(arm) < 1e9:
                log(f"删残臂 {ty} ({os.path.getsize(arm)} B)")
                os.remove(arm)
            if not os.path.isfile(arm):
                log(f"量化 single-type {ty} → {os.path.basename(arm)}")
                # IQ 系列必须有 imatrix，且挨个张量都要有 —— blk.64(MTP) 不在 calib 覆盖内，
                # 直接给纯类型会 assert（Missing importance matrix for blk.64.attn_k.weight）。
                # 所以：能 --pure 的（k-quant）走 --pure；IQ 系列走显式表并把 blk.64 钉 Q8_0。
                cmd = [QUANT]
                if ty.startswith("IQ"):
                    pl = os.path.join(outdir, f"sweep-{ty}-plan.txt")
                    if not os.path.isfile(pl):
                        with open(pl, "w", encoding="utf-8") as pf:
                            for tname in meta:
                                t2 = "Q8_0" if tname.startswith("blk.64.") else ty
                                pf.write("^" + re.escape(tname) + "$=" + t2 + "\n")
                    cmd += ["--imatrix", a.imatrix, "--tensor-type-file", pl]
                else:
                    cmd += ["--imatrix", a.imatrix, "--pure"]
                cmd += [a.bf16, arm, ty, str(a.threads)]
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.returncode != 0:
                    log(f"[SKIP] {ty} 量化失败: {p.stderr.strip()[-200:]}")
                    continue
            log(f"读臂 {ty} ({os.path.getsize(arm)/1e9:.2f} GB)")
            ar = gguf.GGUFReader(arm)
            ameta = {}
            for t in ar.tensors:
                ameta[t.name] = (t.n_bytes, int(t.data_offset), t.tensor_type, tuple(int(x) for x in t.shape))
            del ar
            fah = open(arm, "rb")
            n_ok = 0
            for name, (shape, bpr0, off0, ty0) in meta.items():
                if name not in ameta:
                    continue
                anb, aoff, aty, ashape = ameta[name]
                if ashape != shape:
                    log(f"[SKIP] {name} 形状 {ashape} != {shape}")
                    continue
                R = min(a.rows, shape[1])
                bpr = anb // shape[1]
                if bpr * shape[1] != anb:
                    continue
                try:
                    w = dequantize(read_rows(fh, off0, bpr0, R), ty0).reshape(R, shape[0]).astype(np.float32)
                    q = dequantize(read_rows(fah, aoff, bpr, R), aty).reshape(R, shape[0]).astype(np.float32)
                except Exception as e:
                    log(f"[SKIP] {name} dequant 失败 {type(e).__name__}: {e}")
                    continue
                if q.shape != w.shape:
                    log(f"[SKIP] {name} 形状不符 q{q.shape} w{w.shape}")
                    continue
                diff2 = (q - w) ** 2
                ch = imx.get(name)
                if ch is not None and ch.size == w.shape[1]:
                    wt = ch / max(float(ch.mean()), 1e-12)
                    err = float((diff2 * wt[None, :]).mean())
                else:
                    err = float(diff2.mean())
                fo.write(json.dumps({
                    "tensor": name, "type": ty,
                    "n_elem": int(shape[0]) * int(shape[1]),
                    "bytes_total": int(anb), "rows_sampled": int(R),
                    "wmse": err, "imatrix": bool(ch is not None and ch.size == w.shape[1]),
                }) + "\n")
                n_ok += 1
                del w, q, diff2
            fah.close()
            fo.flush()
            log(f"完成 {ty}: {n_ok} 张量")
            if not a.keep_arms:
                try:
                    os.remove(arm)
                except OSError:
                    pass
                log(f"删臂 {ty}")
    fh.close()
    log(f"全部完成 → {a.out}")


if __name__ == "__main__":
    main()
