# -*- coding: utf-8 -*-
"""用 gguf 库自带的 TensorNameMap 反查 QWEN35 的真值映射

为什么这样做：不猜、不爬源码，直接问库本身
  gguf.TensorNameMap(arch, n_layers) 里存的是 {MODEL_TENSOR: [HF 侧后缀, ...]}
  GGUF 名字由 gguf.TENSOR_NAMES[tensor] + 层号 拼出来
  所以 反查 = 对每个 (tensor, hf_suffix) 组合，生成 GGUF 名与 HF 名

输出：直接可用的 GGUF→HF 映射表（JSON），供 gguf_to_hf.py 使用
"""
import json, sys

try:
    import gguf
except ImportError:
    print("[FATAL] 缺 gguf 库")
    sys.exit(2)

ARCH = gguf.MODEL_ARCH.QWEN35
N_LAYERS = 64          # 从 v6-bf16.gguf 的 block_count 取；先按 64 生成

tm = gguf.TensorNameMap(ARCH, N_LAYERS)
print(f"arch = QWEN35  n_layers = {N_LAYERS}")
print(f"TensorNameMap 类型: {type(tm)}")
print(f"属性: {[a for a in dir(tm) if not a.startswith('_')][:12]}")

# tm.mapping: {MODEL_TENSOR: [hf_suffix, ...]}（第一个是首选）
mapping = getattr(tm, "mapping", None)
if mapping is None:
    print("[FATAL] 没有 .mapping 属性")
    sys.exit(3)

# gguf.TENSOR_NAMES 才是「GGUF 名字模板 → HF 名字候选列表」的真表
mapping = gguf.TENSOR_NAMES
print(f"\nTENSOR_NAMES 类型: {type(mapping)}  条目数: {len(mapping)}")
_k0 = next(iter(mapping))
print(f"样例 key: {_k0!r}  value: {mapping[_k0]!r}")

out = {}   # gguf_name -> hf_name
for g_tmpl, v in mapping.items():
    # v 可能是 [str, ...]（HF 候选名）
    if isinstance(v, (list, tuple)):
        cand = [str(x) for x in v]
    else:
        cand = [str(v)]
    gs = str(g_tmpl)
    if "{bid}" in gs:
        for bid in range(N_LAYERS):
            g = gs.format(bid=bid)
            for h0 in cand:
                if "{bid}" in h0:
                    out[g] = h0.format(bid=bid)
                    break
            else:
                out[g] = cand[0]
    else:
        out[gs] = cand[0]

print(f"\n生成 {len(out)} 条 GGUF→HF 映射")
print("\n=== 非层号条目 ===")
for g, h in out.items():
    if "blk." not in g:
        print(f"  {g:<40} → {h}")

print("\n=== blk.0 的条目（看每层都有什么）===")
for g, h in sorted(out.items()):
    if g.startswith("blk.0."):
        print(f"  {g:<40} → {h}")

json.dump(out, open("/root/autodl-tmp/kitty-rev/logs/v6/MAP-QWEN35.json", "w"),
          indent=1, ensure_ascii=False)
print("\n→ /root/autodl-tmp/kitty-rev/logs/v6/MAP-QWEN35.json")
