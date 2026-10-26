import sys, numpy as np
sys.path.insert(0, "/root/autodl-tmp/lc/gguf-py")
from gguf import GGUFReader
from safetensors import safe_open

G = "/root/autodl-tmp/kitty-rev/gguf/v4-bf16.gguf"
ML = "/root/autodl-tmp/kitty-rev/merged-layers"
r = GGUFReader(G)
d = {t.name: t for t in r.tensors}


def gv(n, k=8):
    t = d[n]
    raw = np.frombuffer(t.data.tobytes(), dtype=np.uint16)[:k]
    return (raw.astype(np.uint32) << 16).view(np.float32)


checks = [("blk.48.ffn_down.weight", 48, "mlp.down_proj.weight"),
          ("blk.55.ffn_up.weight", 55, "mlp.up_proj.weight"),
          ("blk.60.attn_gate.weight", 60, "linear_attn.in_proj_z.weight")]
ok = 0
tot = 0
for gn, lay, hf in checks:
    g = gv(gn)
    p = f"{ML}/layer_{lay}.safetensors"
    try:
        with safe_open(p, framework="pt") as f:
            w = f.get_tensor(f"model.language_model.layers.{lay}.{hf}").float().numpy()
    except Exception as e:
        print(f"  skip {gn}: {e}")
        continue
    W = w.reshape(w.shape[0], -1)
    cands = {"row": W[0, :len(g)], "col": W[:len(g), 0] if W.shape[0] >= len(g) else None,
             "Trow": W.T[0, :len(g)], "Tcol": W.T[:len(g), 0]}
    hit = [k for k, v in cands.items() if v is not None and np.allclose(g, v, atol=1e-2)]
    tot += 1
    ok += 1 if hit else 0
    print(f"  {gn}: gguf[:4]={[round(float(x), 6) for x in g[:4]]} HF[0,:4]={[round(float(x), 6) for x in W[0, :4]]} hit={hit if hit else 'NONE'}")
print(f"[judge9] {ok}/{tot}")
sys.exit(0 if tot > 0 and ok == tot else 2)
