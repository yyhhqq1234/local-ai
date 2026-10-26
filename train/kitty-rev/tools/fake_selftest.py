#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fake_selftest.py —— 用合成 mini-GGUF + mini-HF 验证 gdn_refill.py 的写入/回读/比对逻辑。
不依赖 merged-v4；产物落在 /root/autodl-tmp/tmpwork/gdnfake/。"""
import json, os, struct, subprocess, sys

import numpy as np
import torch
from safetensors.torch import save_file

D = "/root/autodl-tmp/tmpwork/gdnfake"
os.makedirs(D, exist_ok=True)
GG = os.path.join(D, "mini.gguf")
HF = os.path.join(D, "hf")
os.makedirs(HF, exist_ok=True)

# 槽位：ssm_alpha (ne0=in=8, ne1=out=4) F32；ssm_out (ne0=in=8, ne1=out=4) BF16
TENSORS = [
    ("blk.0.ssm_alpha.weight", (8, 4), 0, None),                 # F32
    ("blk.0.ssm_out.weight", (8, 4), 30, "out_proj"),            # BF16
    ("blk.0.attn_qkv.weight", (8, 4), 30, "qkv"),
]
# HF 侧真值（out,in）
hf_out_proj = torch.arange(32, dtype=torch.float32).reshape(4, 8) / 7.0
hf_in_proj_a = torch.arange(32, dtype=torch.float32).reshape(4, 8) / 3.0
hf_qkv = torch.arange(32, dtype=torch.float32).reshape(4, 8) / 11.0
save_file({
    "model.language_model.layers.0.linear_attn.in_proj_a.weight": hf_in_proj_a,
    "model.language_model.layers.0.linear_attn.out_proj.weight": hf_out_proj.bfloat16(),
    "model.language_model.layers.0.linear_attn.in_proj_qkv.weight": hf_qkv.bfloat16(),
}, os.path.join(HF, "model.safetensors"))

# 写 mini GGUF：全部槽位先填零（= 负例现场）
align = 32
infos, blobs, off = [], [], 0
for name, shape, tt, _ in TENSORS:
    n = int(np.prod(shape)) * (4 if tt == 0 else 2)
    infos.append((name, shape, tt, off))
    blobs.append(b"\x00" * n)
    off += n
with open(GG, "wb") as f:
    f.write(b"GGUF" + struct.pack("<I", 3) + struct.pack("<Q", len(TENSORS)) + struct.pack("<Q", 0))
    for name, shape, tt, o in infos:
        nb = name.encode()
        f.write(struct.pack("<Q", len(nb)) + nb)
        f.write(struct.pack("<I", len(shape)) + struct.pack("<%dQ" % len(shape), *shape))
        f.write(struct.pack("<I", tt) + struct.pack("<Q", o))
    pos = f.tell(); ds = (pos + align - 1) // align * align
    f.write(b"\x00" * (ds - pos))
    for b in blobs:
        f.write(b)
print("[fake] gguf=", GG, os.path.getsize(GG), "bytes  hf=", HF)

T = "/root/autodl-tmp/kitty-rev/tools/gdn_refill.py"
PY = sys.executable
print("\n=== 负例（未回填，应报 zero=3）===")
r1 = subprocess.run([PY, T, "--gguf", GG, "--hf", HF, "--check-only", "--log", "/root/autodl-tmp/tmpwork/gdnfake/t.log"],
                    capture_output=True, text=True)
print(r1.stdout.strip()); print("RC=", r1.returncode)

print("\n=== 回填（应写 2 槽位、回读 zero=0、抽检 OK）===")
r2 = subprocess.run([PY, T, "--gguf", GG, "--hf", HF, "--log", "/root/autodl-tmp/tmpwork/gdnfake/t.log"],
                    capture_output=True, text=True)
print(r2.stdout.strip()); print("RC=", r2.returncode)
print("\n=== 回填后复检（应 zero=0）===")
r3 = subprocess.run([PY, T, "--gguf", GG, "--hf", HF, "--check-only", "--log", "/root/autodl-tmp/tmpwork/gdnfake/t.log"],
                    capture_output=True, text=True)
print(r3.stdout.strip().splitlines()[-3] if r3.stdout else ""); print("RC=", r3.returncode)
