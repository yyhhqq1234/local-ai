# -*- coding: utf-8 -*-
"""base-v61 → base-v61b：按 HF 真值形状修张量布局

三类（实测分类，851 个张量）：
  SAME  305  形状已等于 HF        → 原样搬
  TRANS 498  mine == hf[::-1]    → arr.T
  CONV1D 48  mine=[4,10240] hf=[10240,1,4] → arr.T.reshape(hf_shape)

不猜：每个张量都对着 AutoModelForCausalLM 的 state_dict 形状做判定，
三类之外出现任何一个 → 立刻中止，不静默处理。
"""
import json, os, struct, glob, sys

import torch
from safetensors.torch import load_file, save_file
from transformers import AutoConfig, AutoModelForCausalLM

SRC = "/root/autodl-tmp/kitty-rev/base-v61"
DST = "/root/autodl-tmp/kitty-rev/base-v61b"
MAX_SHARD = 5_000_000_000

cfg = AutoConfig.from_pretrained(SRC)
with torch.device("meta"):
    m = AutoModelForCausalLM.from_config(cfg)
hf_shapes = {k: list(v.shape) for k, v in m.state_dict().items()}
print(f"HF 期望 {len(hf_shapes)} 个张量")

os.makedirs(DST, exist_ok=True)

# 先读全部 key -> 所在分片
key2file = {}
for f in sorted(glob.glob(os.path.join(SRC, "*.safetensors"))):
    with open(f, "rb") as fh:
        ln = struct.unpack("<Q", fh.read(8))[0]
        hdr = json.loads(fh.read(ln))
    for k in hdr:
        if k != "__metadata__":
            key2file[k] = f
print(f"源分片 {len(glob.glob(os.path.join(SRC, '*.safetensors')))} 个，key {len(key2file)} 个")

missing = set(hf_shapes) - set(key2file)
extra = set(key2file) - set(hf_shapes)
if missing or extra:
    print(f"[FATAL] key 不匹配 missing={len(missing)} extra={len(extra)}")
    sys.exit(3)

stat = {"same": 0, "trans": 0, "conv": 0}
out, cur_bytes = {}, 0
shard_idx = 0
written = []


def flush():
    global out, cur_bytes, shard_idx
    if not out:
        return
    shard_idx += 1
    name = f"model-{shard_idx:05d}-of-XXXXX.safetensors"
    written.append((name, dict(out)))
    out = {}
    cur_bytes = 0


for f in sorted(glob.glob(os.path.join(SRC, "*.safetensors"))):
    tensors = load_file(f)
    for k, arr in tensors.items():
        hs = hf_shapes[k]
        ms = list(arr.shape)
        if ms == hs:
            new = arr
            stat["same"] += 1
        elif ms == hs[::-1]:
            new = arr.t().contiguous()
            stat["trans"] += 1
        elif len(hs) == 3 and ms == [hs[2], hs[0]]:
            # conv1d 特例：[4,10240] → [10240,1,4]
            new = arr.t().contiguous().reshape(hs)
            stat["conv"] += 1
        else:
            print(f"[FATAL] {k} mine={ms} hf={hs} 不属于三类，中止")
            sys.exit(4)
        assert list(new.shape) == hs, f"{k} 处理后形状仍不对: {list(new.shape)} vs {hs}"
        out[k] = new
        cur_bytes += new.numel() * new.element_size()
        if cur_bytes > MAX_SHARD:
            flush()
flush()

# 真正写盘（先占位命名，再改名带总数）
total = len(written)
index = {"metadata": {"total_size": sum(t.numel() * t.element_size() for _, sh in written for t in sh.values())},
         "weight_map": {}}
for i, (name, sh) in enumerate(written, 1):
    final = name.replace("XXXXX", f"{total:05d}")
    save_file(sh, os.path.join(DST, final))
    for k in sh:
        index["weight_map"][k] = final
    print(f"  写出 {final}  {len(sh)} 张量")

json.dump(index, open(os.path.join(DST, "model.safetensors.index.json"), "w"), indent=2)

# config 与 tokenizer 直接拷（已校验过）
import shutil
for fn in ("config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
           "generation_config.json", "special_tokens_map.json"):
    p = os.path.join(SRC, fn)
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(DST, fn))

print(f"\n统计: SAME={stat['same']} TRANS={stat['trans']} CONV={stat['conv']}")
print(f"分片 {total} 个 → {DST}")
print("\n四条形状断言:")
for k, exp in (("model.embed_tokens.weight", [248320, 5120]),
               ("lm_head.weight", [248320, 5120]),
               ("model.layers.0.mlp.gate_proj.weight", [17408, 5120]),
               ("model.layers.0.mlp.down_proj.weight", [5120, 17408])):
    got = hf_shapes[k]
    print(f"  {k:<46} 期望={exp} 实际={got} {'OK' if got == exp else 'FAIL'}")
