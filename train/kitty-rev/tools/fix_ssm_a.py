#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_ssm_a.py —— 修复 convert_hf_to_gguf 未映射 A_log 导致 ssm_a 全 0 的问题

背景（实测证据）：
  · merged 里有 48 个 `model.language_model.layers.N.linear_attn.A_log`（bf16，取值为负）
  · 由它导出 ssm_a = -exp(A_log) ∈ [-0.3376, -0.00384]，与 v3 的 IQ2_S 完全同量级
  · 但 v4-iq2s-851.gguf 的 `blk.N.ssm_a` 实测 **48 个全 0**（v3 的是真负值）
  · ninfer convert 会做 `if not np.all(ssm_a < 0): raise` ⇒ 直接拒转（gguf_blocks.py:450）

做法：就地修补 GGUF 的 ssm_a（F32，单张量 48 个 float32），值 = -exp(A_log)。
用法：python fix_ssm_a.py --gguf <v4-iq2s-851.gguf> [--merged <merged dir>] [--dry]
"""
import argparse
import json
import os
import struct
import sys

import numpy as np

LE = "<"


def gguf_tensor_offsets(path):
    """返回 (data_start, {tensor_name: (abs_offset, nbytes, ggml_type)})，用 gguf 包读索引"""
    sys.path.insert(0, "/root/autodl-tmp/lc/gguf-py")
    from gguf import GGUFReader
    r = GGUFReader(path)
    # GGUFReader 已把 tensor.offset 转成相对 data 区；data 区起点 = tensor offset 的最小值 - 对齐前的 header 末尾
    # 更稳的做法：用 reader.data offset（部分版本提供），否则按最小 offset 反推
    offs = {}
    min_off = None
    for t in r.tensors:
        o = int(t.offset)
        nb = int(t.nbytes)
        offs[t.name] = (o, nb, int(t.tensor_type))
        if min_off is None or o < min_off:
            min_off = o
    data_start = None
    for attr in ("data_offset", "data_start"):
        if hasattr(r, attr):
            data_start = int(getattr(r, attr))
            break
    if data_start is None:
        # 反推：文件大小 - 所有 tensor 数据总长（假设无 padding 空洞）
        total = sum(v[1] for v in offs.values())
        data_start = os.path.getsize(path) - total
    return data_start, offs


def load_alog(merged_dir):
    idx = json.load(open(os.path.join(merged_dir, "model.safetensors.index.json")))
    wm = idx["weight_map"]
    from safetensors import safe_open
    out = {}
    for k, f in wm.items():
        if not k.endswith("linear_attn.A_log"):
            continue
        # model.language_model.layers.N.linear_attn.A_log
        parts = k.split(".")
        n = int(parts[3])
        with safe_open(os.path.join(merged_dir, f), framework="pt") as sf:
            t = sf.get_tensor(k)
        out[n] = (-np.exp(t.float().numpy().reshape(-1))).astype(np.float32)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--merged", default="/root/autodl-tmp/kitty-rev/merged/Qwen3.8-27B-kittyrev-v4")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    alog = load_alog(a.merged)
    print(f"[load] A_log layers={len(alog)} sample_layer0_minmax=({alog[min(alog)].min():.6f},{alog[min(alog)].max():.6f})")

    data_start, offs = gguf_tensor_offsets(a.gguf)
    print(f"[idx] data_start={data_start} tensors={len(offs)}")

    todo = []
    for n, vals in alog.items():
        name = f"blk.{n}.ssm_a"
        if name not in offs:
            print(f"[warn] {name} 不在 GGUF 中，跳过")
            continue
        off, nb, gtype = offs[name]
        if gtype != 0:
            print(f"[warn] {name} ggml_type={gtype}（期望 0=F32），跳过")
            continue
        if nb != vals.size * 4:
            print(f"[warn] {name} nbytes={nb} 与 48*4 不符，跳过")
            continue
        todo.append((name, data_start + off, vals))

    print(f"[plan] 待修补 {len(todo)} 个张量，共 {len(todo)*192} 字节")
    if a.dry:
        print("[dry] 不写盘")
        return 0

    wrote = 0
    with open(a.gguf, "r+b") as f:
        for name, abs_off, vals in todo:
            f.seek(abs_off)
            buf = vals.astype(LE + "f4").tobytes()
            f.write(buf)
            wrote += 1
        f.flush()
        os.fsync(f.fileno())
    print(f"[write] 已写 {wrote} 个 ssm_a")

    # 回读校验
    sys.path.insert(0, "/root/autodl-tmp/lc/gguf-py")
    from gguf import GGUFReader
    r = GGUFReader(a.gguf)
    bad = 0
    for t in r.tensors:
        if t.name.endswith(".ssm_a"):
            arr = np.array(t.data, dtype=np.float32).reshape(-1)
            if not np.all(arr < 0):
                bad += 1
                print(f"[FAIL] {t.name} 仍有非负值：min={arr.min()}")
    print(f"[verify] ssm_a 非法张量数={bad}")
    print("[VERDICT]", "PASS" if bad == 0 else "FAIL")
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
