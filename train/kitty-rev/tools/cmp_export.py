import sys, glob
import numpy as np
sys.path.insert(0, "/root/autodl-tmp/lc/gguf-py")
from gguf import GGUFReader
from safetensors import safe_open

G = "/root/autodl-tmp/kitty-rev/gguf/v4-bf16.gguf"
ML = "/root/autodl-tmp/kitty-rev/merged-layers"
r = GGUFReader(G)
d = {t.name: t for t in r.tensors}

# gguf 名 -> HF 名（Qwen3.5 混合层：linear_attn 层用 in_proj_*，full-attn 层用 q/k/v_proj）
MAP = [
    ("attn_qkv.weight", ["linear_attn.in_proj_qkv.weight", "self_attn.q_proj.weight"]),
    ("attn_gate.weight", ["linear_attn.in_proj_z.weight", "self_attn.q_proj.weight"]),
    ("attn_norm.weight", ["input_layernorm.weight"]),
    ("post_attention_norm.weight", ["post_attention_layernorm.weight"]),
    ("ffn_down.weight", ["mlp.down_proj.weight"]),
    ("ffn_gate.weight", ["mlp.gate_proj.weight"]),
    ("ffn_up.weight", ["mlp.up_proj.weight"]),
    ("ssm_out.weight", ["linear_attn.out_proj.weight"]),
    ("ssm_alpha.weight", ["linear_attn.in_proj_a.weight"]),
    ("ssm_beta.weight", ["linear_attn.in_proj_b.weight"]),
]


def gv(n, k=8):
    t = d.get(n)
    if t is None:
        return None
    if int(t.tensor_type) == 30:
        raw = np.frombuffer(t.data.tobytes(), dtype=np.uint16)[:k]
        return (raw.astype(np.uint32) << 16).view(np.float32)
    if int(t.tensor_type) == 0:
        return np.frombuffer(t.data.tobytes(), dtype=np.float32)[:k]
    return None


match = 0
zero = 0
mismatch = 0
missing = 0
detail = []
for lay in range(48, 64):
    p = f"{ML}/layer_{lay}.safetensors"
    try:
        sf = safe_open(p, framework="pt")
    except Exception:
        continue
    keys = list(sf.keys())
    for gname, cands in MAP:
        gn = f"blk.{lay}.{gname}"
        g = gv(gn)
        if g is None:
            missing += 1
            continue
        hk = None
        for c in cands:
            k = f"model.language_model.layers.{lay}.{c}"
            if k in keys:
                hk = k
                break
        if hk is None:
            missing += 1
            continue
        w = sf.get_tensor(hk).float().numpy()
        W = w.reshape(w.shape[0], -1)
        if np.all(g == 0):
            zero += 1
            detail.append((gn, "ZERO"))
            continue
        hit = False
        for v in (W[0, :len(g)], W.T[0, :len(g)]):
            if np.allclose(g, v, atol=1e-2):
                hit = True
                break
        if hit:
            match += 1
        else:
            mismatch += 1
            detail.append((gn, "MISMATCH"))
    sf.__exit__()
print(f"[cmp] match={match} zero={zero} mismatch={mismatch} missing={missing}")
for x in detail[:10]:
    print("   ", x)
