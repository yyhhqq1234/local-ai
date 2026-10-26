from gguf import GGUFReader
import numpy as np

for path in ("gguf/v5-iq2s.gguf", "gguf/v61-iq2s-fix.gguf", "gguf/v61-mtp2.gguf"):
    try:
        r = GGUFReader("/root/autodl-tmp/kitty-rev/" + path)
    except Exception as e:
        print(path, "FAIL", e); continue
    print("=" * 70)
    print(path)
    kinds = {}
    for t in r.tensors:
        n = t.name
        key = None
        if n.endswith("ssm_alpha.weight"): key = "ssm_alpha"
        elif n.endswith("ssm_beta.weight"): key = "ssm_beta"
        elif n.endswith("ssm_a"): key = "ssm_a"
        elif n.endswith("ssm_dt.bias"): key = "ssm_dt.bias"
        elif n.endswith("ssm_conv1d.weight"): key = "ssm_conv1d"
        elif n.endswith("ssm_norm.weight"): key = "ssm_norm"
        elif n.endswith("ssm_out.weight"): key = "ssm_out"
        if key:
            kinds.setdefault(key, set()).add(t.tensor_type.name)
    for k in sorted(kinds):
        print(f"  {k:<14} {sorted(kinds[k])}")
    # 抽样 blk.0 / blk.12 的 ssm_a 值域
    for t in r.tensors:
        if t.name in ("blk.0.ssm_a", "blk.12.ssm_a"):
            a = t.data.astype(np.float32)
            print(f"    {t.name}: type={t.tensor_type.name} min={a.min():.6g} max={a.max():.6g} n={a.size}")
