"""cmp_hf_gguf.py —— 直接比对 HF safetensors 与 gguf 同名张量的数值（判断导出是否正确）

用法：python cmp_hf_gguf.py <hf_dir> <gguf> [tensor_pair]
"""
import json
import os
import struct
import sys

import numpy as np
import gguf

hf_dir, gp = sys.argv[1], sys.argv[2]
pairs = [("model.layers.0.mlp.gate_proj.weight", "blk.0.ffn_gate.weight"),
         ("model.layers.0.linear_attn.in_proj_qkv.weight", "blk.0.attn_qkv.weight"),
         ("model.embed_tokens.weight", "token_embd.weight"),
         ("model.norm.weight", "output_norm.weight")]
if len(sys.argv) > 3:
    pairs = [(sys.argv[3], sys.argv[4])]


def hf_read(name):
    for sh in sorted(f for f in os.listdir(hf_dir) if f.endswith('.safetensors')):
        p = os.path.join(hf_dir, sh)
        with open(p, 'rb') as f:
            n = struct.unpack('<Q', f.read(8))[0]
            hdr = json.loads(f.read(n).decode())
            if name not in hdr:
                continue
            v = hdr[name]
            s, e = v['data_offsets']
            f.seek(8 + n + s)
            buf = f.read(e - s)
            dt = v['dtype']
            if dt == 'BF16':
                return ((np.frombuffer(buf, dtype='<u2').astype(np.uint32) << 16).view(np.float32)).reshape(v['shape'])
            if dt == 'F32':
                return np.frombuffer(buf, dtype='<f4').reshape(v['shape'])
            return None
    return None


r = gguf.GGUFReader(gp)
gmap = {t.name: t for t in r.tensors}
for hname, gname in pairs:
    a = hf_read(hname)
    t = gmap.get(gname)
    if a is None or t is None:
        print(f'[skip] {hname} / {gname}  a={a is not None} t={t is not None}')
        continue
    raw = np.array(t.data)
    if raw.dtype == np.uint8 and t.tensor_type == 0:  # F32
        b = raw.view('<f4').astype('float32')
    elif raw.dtype == np.uint8 and t.tensor_type in (1, 30):  # F16/BF16 以字节返回
        b = ((np.frombuffer(raw.tobytes(), dtype='<u2').astype(np.uint32) << 16).view(np.float32)
             if t.tensor_type == 30 else np.frombuffer(raw.tobytes(), dtype='<f2').astype('float32'))
    else:
        b = raw.astype('float32')
    a = a.astype('float32').ravel()
    b = b.ravel()
    n = min(a.size, b.size, 100000)
    a2, b2 = a[:n], b[:n]
    print(f'--- {hname} vs {gname}  shape hf={a.size} gguf={b.size}')
    print('    hf   mean|w|=%.4e max=%.4e  first3=%s' % (np.abs(a2).mean(), np.abs(a2).max(), a2[:3]))
    print('    gguf mean|w|=%.4e max=%.4e  first3=%s' % (np.abs(b2).mean(), np.abs(b2).max(), b2[:3]))
    if a2.size == b2.size:
        d = np.abs(a2 - b2)
        print('    max|diff|=%.3e  rel=%.3e' % (d.max(), d.max() / (np.abs(a2).max() + 1e-9)))
