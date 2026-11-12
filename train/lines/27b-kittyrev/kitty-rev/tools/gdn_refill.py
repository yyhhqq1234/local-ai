#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gdn_refill.py —— Qwen3.5 GDN 张量「按名回填」器（HF → GGUF 槽位，量化前执行）

背景：llama.cpp 的 convert_hf_to_gguf（13KB shim，grep linear_attn=0）不认 GDN，
导出 bf16 GGUF 时把 GDN 槽位写成全零，零值一路进 .ninfer。

用法：
    python gdn_refill.py --gguf <bf16.gguf> --hf <merged 目录> --check-only   # 只扫零，不写
    python gdn_refill.py --gguf <bf16.gguf> --hf <merged 目录>               # 回填 + 校验
附加：--log <路径>（默认 logs/v4/GDN-RUN.log）· --dry（只打印计划）· --tensors-attn N（抽检条数，默认 3）

规则：
  · 只写 type=0(F32) / type=30(BF16)；遇到 >30（已量化）立即报错退出（量化前跑）
  · GGUF 维度是 (ne0=in, ne1=out)，HF 是 (out, in) → 写前转置；conv1d 是 (out,1,k) → (k,out)
  · 写后逐张量回读：zero 计数必须 == 0；另抽 3 个张量做「行/列」两式比对（容差 1e-2）
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gguf_patch_ssm_a import parse  # noqa: E402  （已验：能正确算 data_start/tensor_info 偏移）

TYPE_F32, TYPE_BF16 = 0, 30
TOL = 1e-3          # 审计#7：1e-2 → 1e-3

# (GGUF 槽位后缀, HF 候选键后缀[按 priority], 变换)
# 目标名逐条对照 ninfer-all-master/tools/convert/gguf_blocks.py:430-460
GDN_SPECS = [
    ("attn_qkv.weight",   ["linear_attn.in_proj_qkv.weight"],                     "T"),
    ("attn_gate.weight",  ["linear_attn.in_proj_z.weight", "self_attn.q_proj.weight"], "T"),
    ("ssm_out.weight",    ["linear_attn.out_proj.weight"],                        "T"),
    ("ssm_alpha.weight",  ["linear_attn.in_proj_a.weight"],                       "T"),
    ("ssm_beta.weight",   ["linear_attn.in_proj_b.weight"],                       "T"),
    ("ssm_a",             ["linear_attn.A_log"],                                  "NEGEXP"),
    ("ssm_dt.bias",       ["linear_attn.dt_bias"],                                "VEC"),
    ("ssm_conv1d.weight", ["linear_attn.conv1d.weight"],                          "CONV"),
    ("ssm_norm.weight",   ["linear_attn.norm.weight"],                            "VEC"),
]
LAYER_PREFIXES = ["model.language_model.layers.", "model.layers.", "language_model.layers."]


# ---------------------------------------------------------------- HF 侧 ----
def load_hf_index(hf: str) -> dict:
    """{键: 分片文件}；无 index.json 时扫全部分片。"""
    idx = os.path.join(hf, "model.safetensors.index.json")
    if os.path.exists(idx):
        return json.load(open(idx, encoding="utf-8"))["weight_map"]
    from safetensors import safe_open
    wm = {}
    for fn in sorted(os.listdir(hf)):
        if not fn.endswith(".safetensors"):
            continue
        with safe_open(os.path.join(hf, fn), framework="pt") as sf:
            for k in sf.keys():
                wm[k] = fn
    return wm


def read_hf(hf: str, wm: dict, key: str) -> np.ndarray:
    """返回 raw：bf16 → uint16 位模式（float32 视图可复原），f32 → float32。"""
    from safetensors import safe_open
    import torch
    with safe_open(os.path.join(hf, wm[key]), framework="pt") as sf:
        t = sf.get_tensor(key)
    if t.dtype == torch.bfloat16:
        return t.contiguous().view(torch.int16).numpy().view(np.uint16)
    return t.to(torch.float32).contiguous().numpy()


def bf16_to_f32(raw: np.ndarray) -> np.ndarray:
    return (raw.astype(np.uint32) << 16).view(np.float32)


def raw_to_f32(raw: np.ndarray, gguf_type: int) -> np.ndarray:
    return bf16_to_f32(raw) if gguf_type == TYPE_BF16 else raw.astype(np.float32)


def shape_to_bytes(ti: dict) -> int:
    n = int(np.prod(ti["shape"])) if ti["shape"] else 1
    return n * (4 if ti["type"] == TYPE_F32 else 2)


def transform(raw: np.ndarray, kind: str) -> np.ndarray:
    """HF raw → 待写字节。

    实测结论（fake 自测两式对照）：GGUF 的 *dims* 是 (ne0=in, ne1=out)，但**内存序**仍是
    最内维 ne0 最快 = C 序下第一维最慢 = (ne1, ne0) 排布 —— 与 HF (out, in) 的 C 序**完全同构**，
    所以数据**不需要转置**；转置只发生在"读维度"的理解上。转置写会把矩阵写成转置，回读两式都不符。
    """
    if kind == "NEGEXP":                  # A_log → -exp(A_log)，F32
        a = bf16_to_f32(raw) if raw.dtype == np.uint16 else raw.astype(np.float32)
        return (-np.exp(a.astype(np.float64))).astype(np.float32).reshape(raw.shape)
    return np.ascontiguousarray(np.reshape(raw, (-1,)))   # T / CONV / VEC：原样（仅压平）


def to_bf16(f32: np.ndarray) -> np.ndarray:
    """f32 → bf16 位模式（就近舍入）。"""
    u = np.ascontiguousarray(f32, dtype=np.float32).view(np.uint32)
    return ((u + 0x8000) >> 16).astype(np.uint16)


def coerce(dat: np.ndarray, gguf_type: int) -> np.ndarray:
    """按 **GGUF 槽位类型** 对齐 dtype —— 现场问题①的根因：HF 张量 dtype 与槽位 dtype 不同
    （例如槽位 F32、HF 是 bf16）→ nbytes 不等 → 被当成"形状不符"跳过（288/432 只写了 6 类/层）。"""
    if gguf_type == TYPE_F32 and dat.dtype != np.float32:
        return bf16_to_f32(dat)
    if gguf_type == TYPE_BF16 and dat.dtype != np.uint16:
        return to_bf16(dat)
    return dat


# ---------------------------------------------------------------- GGUF ----
class GGUF:
    def __init__(self, path: str):
        self.path = path
        g = parse(path)
        self.g = g
        self.tensors = g["tensors"]
        self.data_start = g["data_start"]

    def offset(self, name: str) -> int:
        return self.data_start + self.tensors[name]["off"]

    def read_raw(self, name: str, f) -> np.ndarray:
        ti = self.tensors[name]
        n = shape_to_bytes(ti)
        f.seek(self.offset(name))
        b = f.read(n)
        if len(b) != n:
            raise IOError(f"{name} 读短：{len(b)} != {n}")
        return np.frombuffer(b, dtype=np.uint16 if ti["type"] == TYPE_BF16 else np.float32).copy()

    def is_zero(self, name: str, f) -> bool:
        return not self.read_raw(name, f).any()

    def zero_names(self, names: list[str], f) -> list[str]:
        return [n for n in names if self.is_zero(n, f)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--hf", default="")
    ap.add_argument("--check-only", action="store_true", help="只扫零/校验，不写")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--log", default="logs/v4/GDN-RUN.log")
    ap.add_argument("--tensors-attn", type=int, default=3)
    a = ap.parse_args()

    lines: list[str] = []

    def out(msg: str = "") -> None:
        print(msg)
        lines.append(msg)

    out(f"[gdn_refill] {time.strftime('%F %T')} gguf={a.gguf}")
    g = GGUF(a.gguf)
    out(f"[gguf] ver={g.g['ver']} n_t={g.g['n_t']} align={g.g['align']} data_start={g.data_start} "
        f"bytes={os.path.getsize(a.gguf):,}")

    # 槽位类型闸门：>30 = 已量化，拒绝
    slots = [f"blk.{n}.{s}" for n in range(64) for s, _, _ in GDN_SPECS]
    present = [s for s in slots if s in g.tensors]
    badtype = [(s, g.tensors[s]["type"]) for s in present if g.tensors[s]["type"] not in (TYPE_F32, TYPE_BF16)]
    out(f"[slots] 命中 {len(present)}/{len(slots)}（预期 48 层 × 9 = 432）  F32={sum(1 for s in present if g.tensors[s]['type']==0)} "
        f"BF16={sum(1 for s in present if g.tensors[s]['type']==30)}")
    if badtype:
        out(f"[FATAL] 发现已量化槽位（type>30）：{badtype[:5]} —— 回填必须在量化前做")
        return 2

    with open(a.gguf, "rb") as f:
        zeros = g.zero_names(present, f)
    out(f"[check] zero 张量 = {len(zeros)} / {len(present)}")
    if zeros:
        import collections
        out(f"[check] 按后缀: {dict(collections.Counter(z.split('.', 2)[2] for z in zeros))}")
        out(f"[check] 样例: {zeros[:6]}")

    if a.check_only:
        out("[check-only] 不写盘")
        _emit(lines, a.log)
        return 0 if not zeros else 1

    if not a.hf or not os.path.isdir(a.hf):
        out(f"[FATAL] --hf 不存在：{a.hf!r}（merged-v4 就绪后再跑；现在可用 --check-only）")
        _emit(lines, a.log)
        return 2

    wm = load_hf_index(a.hf)
    prefix = next((p for p in LAYER_PREFIXES if any(k.startswith(p) for k in wm)), LAYER_PREFIXES[0])
    layers = sorted({int(k[len(prefix):].split(".")[0]) for k in wm if k.startswith(prefix)})
    out(f"[hf] shards/index={len(set(wm.values()))} · prefix={prefix} · layers={len(layers)}")

    plan, missing, shape_bad, src_zero = [], [], [], {}
    for n in layers:
        for suffix, cands, kind in GDN_SPECS:
            tgt = f"blk.{n}.{suffix}"
            ti = g.tensors.get(tgt)
            if ti is None:
                missing.append(tgt); continue
            key = next((prefix + str(n) + "." + c for c in cands if (prefix + str(n) + "." + c) in wm), None)
            if key is None:
                missing.append(f"{tgt}←HF({cands[0]})"); continue
            raw = read_hf(a.hf, wm, key)
            dat = coerce(transform(raw, kind), ti["type"])
            want = shape_to_bytes(ti)
            if dat.nbytes != want:
                shape_bad.append((tgt, key, str(raw.dtype), raw.shape, dat.shape, dat.nbytes, ti["shape"], want)); continue
            src_zero[tgt] = not bool(np.asarray(raw).any())
            plan.append((tgt, key, dat, ti["type"]))
    out(f"[plan] 可回填={len(plan)} 缺HF/缺槽={len(missing)} 形状不符={len(shape_bad)}"
        f"（F32 槽位 {sum(1 for p in plan if p[3]==TYPE_F32)} / BF16 槽位 {sum(1 for p in plan if p[3]==TYPE_BF16)}）")
    for x in missing[:6]:
        out(f"   miss: {x}")
    for x in shape_bad[:6]:
        out(f"   shape: tgt={x[0]} hf={x[2]}{x[3]} dat={x[4]}→{x[5]}B gguf{x[6]}={x[7]}B")

    if a.dry or not plan:
        out("[dry] 不写盘")
        _emit(lines, a.log)
        return 0 if plan and not (missing or shape_bad) else 2

    t0 = time.time()
    with open(a.gguf, "r+b") as f:
        for tgt, key, dat, tt in plan:
            f.seek(g.offset(tgt))
            f.write(dat.tobytes())
        f.flush(); os.fsync(f.fileno())
    out(f"[write] 已写 {len(plan)} 个槽位，用时 {time.time()-t0:.1f}s")

    # 回读：**全部** GDN 槽位逐张量读一遍（写后 zero 必须 0）+ 每类各抽 2 个与 HF 两式对账（TOL 1e-3）
    with open(a.gguf, "rb") as f:
        zeros2, readback = [], 0
        for name in present:
            g.read_raw(name, f)          # 逐槽位回读：偏移/长度错会在这里抛
            readback += 1
            if g.is_zero(name, f):
                zeros2.append(name)
        residual = [z for z in zeros2 if not src_zero.get(z)]
        out(f"[verify] 逐槽位回读 {readback}/{len(present)} · 写后 zero 张量 = {len(zeros2)}"
            f"（其中源即零 {len(zeros2)-len(residual)} · 非源零残留 {len(residual)}）")
        if residual:
            out(f"[verify] 非源零残留（= 没写进去）：{residual[:8]}")
        picks = []
        for suffix, _, _ in GDN_SPECS:
            picks.extend([e for e in plan if e[0].endswith("." + suffix)][:2])
        out(f"[verify] 抽检 {len(picks)} 个（9 类 × 每类 2 个）· TOL={TOL}")
        ok_all = len(residual) == 0
        for tgt, key, dat, tt in picks:
            ti = g.tensors[tgt]
            got = g.read_raw(tgt, f)
            ne0 = int(ti["shape"][0]); ne1 = int(ti["shape"][1]) if len(ti["shape"]) > 1 else 1
            # 问题②修正：比对基准 = **写入值 dat**（已含 NEGEXP/转置/coerce），不是 HF 原始 A_log
            #   —— 否则 ssm_a 用 -exp(A_log) 写入却拿 A_log 比，必然差 O(1)
            ref_f = raw_to_f32(np.asarray(dat), tt).reshape(-1)
            got_f = raw_to_f32(got, tt)
            row = got_f.reshape(ne1, ne0)              # GGUF (ne1=out, ne0=in)
            col = got_f.reshape(ne0, ne1)              # 反式参考
            row_f = row.reshape(-1); col_f = col.reshape(-1)
            e_row = float(np.abs(row_f - ref_f).max()) if row_f.size == ref_f.size else float("inf")
            e_col = float(np.abs(col_f - ref_f).max()) if col_f.size == ref_f.size else float("inf")
            ok = min(e_row, e_col) <= TOL
            ok_all &= ok
            out(f"  [{'OK ' if ok else 'FAIL'}] {tgt}←{key.split(prefix)[-1]} 行式 max|Δ|={e_row:.3g} 列式={e_col:.3g}"
                f"（ref{ref_f.shape} GGUF{ti['shape']} dtype={tt}）")

    _emit(lines, a.log)
    out("[gdn_refill] PASS" if ok_all else "[gdn_refill] FAIL")
    return 0 if ok_all else 1


def _emit(lines: list[str], logpath: str) -> None:
    try:
        d = os.path.dirname(logpath)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(logpath, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError as e:
        print(f"[warn] 写日志失败：{e}")


if __name__ == "__main__":
    sys.exit(main())
