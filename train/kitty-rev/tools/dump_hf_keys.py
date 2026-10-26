# -*- coding: utf-8 -*-
"""终极真值：让 transformers 自己说出它需要哪些参数名

方法：用 cfg-vision 的 config 在 meta device 上建一个空模型（不占内存），
     列出 state_dict 的 key —— 这就是 HF 侧接受的**完整参数名集合**，
     与 gguf 里的张量名一一对照即可取得正确映射，不需要猜。

在远程跑：
  /root/miniconda3/bin/python tools/dump_hf_keys.py
"""
import json, sys, collections

CFG = "/root/autodl-tmp/kitty-rev/cfg-vision"

try:
    import torch
    from transformers import AutoConfig, AutoModel
except ImportError as e:
    print(f"[FATAL] 依赖缺失: {e}")
    sys.exit(2)

cfg = AutoConfig.from_pretrained(CFG)
print(f"config class: {type(cfg).__name__}")
print(f"architectures: {getattr(cfg, 'architectures', None)}")
print(f"model_type: {getattr(cfg, 'model_type', None)}")

try:
    with torch.device("meta"):
        model = AutoModel.from_config(cfg)
except Exception as e:
    print(f"[FATAL] 建模失败: {type(e).__name__}: {e}")
    sys.exit(3)

keys = list(model.state_dict().keys())
print(f"\nstate_dict 共 {len(keys)} 个 key")

# 按"去掉层号"聚合
pat = collections.Counter()
for k in keys:
    kk = k.replace("model.language_model.layers.", "L.").replace("model.", "")
    import re
    kk = re.sub(r"L\.\d+\.", "L.N.", kk)
    kk = re.sub(r"\.\d+\.", ".N.", kk)
    pat[kk] += 1

print(f"\n=== 参数名模式（{len(pat)} 种）===")
for p, n in sorted(pat.items(), key=lambda x: (-x[1], x[0])):
    print(f"  {n:>4} × {p}")

# 单独列出 layer 0 的全部参数（用于精确对号）
print("\n=== 第 0 层全部参数 ===")
for k in keys:
    if ".layers.0." in k or k.endswith("embed_tokens.weight") or k.endswith("norm.weight") or k.startswith("lm_head"):
        print(f"  {k}")

json.dump({"n": len(keys), "patterns": {p: n for p, n in pat.items()}, "keys": keys[:500]},
          open("/root/autodl-tmp/kitty-rev/logs/v6/HF-KEYS.json", "w"), indent=1, ensure_ascii=False)
print("\n→ /root/autodl-tmp/kitty-rev/logs/v6/HF-KEYS.json")
