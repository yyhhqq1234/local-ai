#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gguf_patch_ssm_a.py —— 直接按 GGUF v3 规范解析表头并就地修补 ssm_a（不依赖 gguf 包的 ReaderTensor 属性）

背景：convert_hf_to_gguf 未把 HF 的 `linear_attn.A_log` 映射成 `ssm_a`，v4 的 48 个 blk.N.ssm_a 全 0；
      ninfer convert 要求 `np.all(ssm_a < 0)`（gguf_blocks.py:450）⇒ 必须补回 -exp(A_log)。
用法：
  python gguf_patch_ssm_a.py --gguf <path> [--merged <dir>] [--dry]
"""
import argparse, json, os, struct, sys
import numpy as np

# GGUF value types
T_U8, T_I8, T_U16, T_I16, T_U32, T_I32, T_F32, T_BOOL, T_STR, T_ARR, T_U64, T_I64, T_F64 = range(13)

SCALAR = {T_U8: ("<B", 1), T_I8: ("<b", 1), T_U16: ("<H", 2), T_I16: ("<h", 2), T_U32: ("<I", 4),
          T_I32: ("<i", 4), T_F32: ("<f", 4), T_BOOL: ("<?", 1), T_U64: ("<Q", 8), T_I64: ("<q", 8), T_F64: ("<d", 8)}


def rd_str(f):
    (n,) = struct.unpack("<Q", f.read(8))
    return f.read(n).decode("utf-8", "replace")


def skip_val(f, vt):
    if vt in SCALAR:
        fmt, sz = SCALAR[vt]
        f.read(sz)
    elif vt == T_STR:
        rd_str(f)
    elif vt == T_ARR:
        (it,) = struct.unpack("<I", f.read(4))
        (n,) = struct.unpack("<Q", f.read(8))
        for _ in range(n):
            skip_val(f, it)
    else:
        raise ValueError(f"unknown gguf value type {vt}")


def parse(path):
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"GGUF":
            raise ValueError("not a gguf")
        ver, = struct.unpack("<I", f.read(4))
        n_tensors, = struct.unpack("<Q", f.read(8))
        n_kv, = struct.unpack("<Q", f.read(8))
        align = 32
        for _ in range(n_kv):
            k = rd_str(f)
            vt, = struct.unpack("<I", f.read(4))
            if k == "general.alignment" and vt in SCALAR:
                fmt, sz = SCALAR[vt]
                align = struct.unpack(fmt, f.read(sz))[0]
            else:
                skip_val(f, vt)
        tensors = {}
        for _ in range(n_tensors):
            name = rd_str(f)
            nd, = struct.unpack("<I", f.read(4))
            dims = struct.unpack("<%dQ" % nd, f.read(8 * nd))
            tt, = struct.unpack("<I", f.read(4))
            off, = struct.unpack("<Q", f.read(8))
            tensors[name] = {"shape": dims, "type": tt, "off": off}
        pos = f.tell()
        data_start = (pos + align - 1) // align * align
    return {"ver": ver, "n_t": n_tensors, "align": align, "tensors": tensors, "data_start": data_start}


def load_alog(merged_dir):
    idx = json.load(open(os.path.join(merged_dir, "model.safetensors.index.json")))
    wm = idx["weight_map"]
    from safetensors import safe_open
    out = {}
    for k, fn in wm.items():
        if not k.endswith("linear_attn.A_log"):
            continue
        n = int(k.split(".")[3])
        with safe_open(os.path.join(merged_dir, fn), framework="pt") as sf:
            t = sf.get_tensor(k)
        out[n] = (-np.exp(t.float().numpy().reshape(-1))).astype("<f4")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gguf", required=True)
    ap.add_argument("--merged", default="/root/autodl-tmp/kitty-rev/merged/Qwen3.8-27B-kittyrev-v4")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    g = parse(a.gguf)
    print(f"[gguf] ver={g['ver']} n_t={g['n_t']} align={g['align']} data_start={g['data_start']}")
    alog = load_alog(a.merged)
    print(f"[merged] A_log layers={len(alog)}")

    todo, miss, wrong = [], [], []
    for n, vals in sorted(alog.items()):
        name = f"blk.{n}.ssm_a"
        ti = g["tensors"].get(name)
        if ti is None:
            miss.append(name); continue
        if ti["type"] != 0:
            wrong.append((name, ti["type"])); continue
        expect_bytes = int(np.prod(ti["shape"])) * 4
        if expect_bytes != vals.nbytes:
            wrong.append((name, f"bytes {expect_bytes}!={vals.nbytes}")); continue
        todo.append((name, g["data_start"] + ti["off"], vals))

    print(f"[plan] 可修补={len(todo)} 缺失={len(miss)} 类型/长度不符={len(wrong)}")
    if miss[:3]: print("   miss:", miss[:3])
    if wrong[:3]: print("   wrong:", wrong[:3])
    if a.dry or not todo:
        return 0

    with open(a.gguf, "r+b") as f:
        for name, abs_off, vals in todo:
            f.seek(abs_off)
            f.write(vals.tobytes())
        f.flush(); os.fsync(f.fileno())
    print(f"[write] {len(todo)} 个 ssm_a 已写")

    # 回读校验（直接按偏移读回原字节）
    bad = 0
    with open(a.gguf, "rb") as f:
        for name, abs_off, vals in todo:
            f.seek(abs_off)
            back = np.frombuffer(f.read(vals.nbytes), dtype="<f4")
            if not np.all(back < 0) or not np.allclose(back, vals, rtol=0, atol=0):
                bad += 1
                print(f"[FAIL] {name} 回读不符")
    print(f"[verify] 回读不符数={bad}")
    n_ssm = sum(1 for k in g["tensors"] if k.endswith(".ssm_a"))
    print(f"[info] GGUF 中 ssm_a 张量共 {n_ssm} 个")
    print("[VERDICT]", "PASS" if bad == 0 else "FAIL")
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
