# -*- coding: utf-8 -*-
"""把 blk.12.ssm_a 里的 -0.0 改成极小负数（保留其余 47 个值不动）

为什么只改字节：ssm_a 是 F32(4B/值)，48 个值 = 192 B；整文件重写 9.7G 不值，
              直接用 gguf reader 拿到 data_offset，seek 改 4 字节即可。
"""
import struct, sys
import numpy as np
from gguf import GGUFReader

P = "/root/autodl-tmp/kitty-rev/gguf/v61-mtp2.gguf"
TARGET = "blk.12.ssm_a"
FIX = -1e-6          # 极小负数，保证 < 0 且不影响 -exp(A) 的量级

r = GGUFReader(P)
t = next((x for x in r.tensors if x.name == TARGET), None)
if t is None:
    print("[FATAL] 找不到", TARGET); sys.exit(2)

a = t.data.astype(np.float32)
bad = np.where(a >= 0)[0]
print(f"{TARGET}: dtype={a.dtype} n={a.size} 非负索引={bad.tolist()}")
if bad.size == 0:
    print("已全为负，无需修改"); sys.exit(0)

off = int(t.data_offset)
print(f"data_offset={off} 文件大小={__import__('os').path.getsize(P)}")

with open(P, "r+b") as f:
    for idx in bad:
        pos = off + int(idx) * 4
        f.seek(pos)
        old = f.read(4)
        f.seek(pos)
        f.write(struct.pack("<f", FIX))
        f.seek(pos)
        new = f.read(4)
        print(f"  idx={idx} @0x{pos:x} {old.hex()} -> {new.hex()}  ({struct.unpack('<f', old)[0]} -> {struct.unpack('<f', new)[0]})")

# 回读校验
r2 = GGUFReader(P)
t2 = next(x for x in r2.tensors if x.name == TARGET)
a2 = t2.data.astype(np.float32)
print(f"\n回读: min={a2.min():.6g} max={a2.max():.6g} 非负个数={int((a2>=0).sum())}")
print("VERDICT=", "PASS" if (a2 >= 0).sum() == 0 else "FAIL")
