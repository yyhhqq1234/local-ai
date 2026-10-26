import sys, struct, os
import numpy as np
from gguf import GGUFReader

P = sys.argv[1] if len(sys.argv) > 1 else "/root/autodl-tmp/kitty-rev/gguf/v61-bf16ssm-mtp.gguf"
FIX = -1e-6
r = GGUFReader(P)
fixed = 0
for t in r.tensors:
    if not t.name.endswith("ssm_a"):
        continue
    a = t.data.astype(np.float32)
    bad = np.where(a >= 0)[0]
    if bad.size == 0:
        continue
    off = int(t.data_offset)
    with open(P, "r+b") as f:
        for idx in bad:
            pos = off + int(idx) * 4
            f.seek(pos); f.write(struct.pack("<f", FIX))
    print(f"  {t.name}: fixed {bad.size} at idx {bad.tolist()}")
    fixed += int(bad.size)
print("TOTAL_FIXED =", fixed)

r2 = GGUFReader(P)
bad2 = 0
for t in r2.tensors:
    if t.name.endswith("ssm_a"):
        a = t.data.astype(np.float32)
        bad2 += int((a >= 0).sum())
print("RECHECK_NONNEG =", bad2)
