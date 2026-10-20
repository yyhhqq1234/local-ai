# 05 · 模型身份核实（Qwen3.8 vs `Qwen3_5*` 类名）

> 起因：评估过程中曾把 `model_type = qwen3_5_text` 误读为"模型是 Qwen3.5"，被操作者指出。本文件固化核实过程与结论，防止后续再犯。

---

## 1 结论

| 项 | 值 |
|---|---|
| 模型产品名 | **Qwen3.8-27B** |
| 部署档 | `huihui-ai` 的 abliterated 版 + Swift-1.5 处理后，GSQ-RCO 量化到 **IQ2_S**，加 MTP 头 |
| HF 顶层 `architectures` | `Qwen3_5ForConditionalGeneration` |
| HF `model_type` | `qwen3_5` |
| text 子配置 `architectures` | `Qwen3_5ForCausalLM` |
| text 子配置 `model_type` | `qwen3_5_text` |
| `Qwen3_5*` 的正确含义 | **transformers 实现类名**，不是模型版本号 |
| 类比 | Qwen2.5 至今仍写 `Qwen2ForCausalLM`；Qwen3 早期仍写 `Qwen3ForCausalLM` |

---

## 2 本地容器 config（实测 dump，权威）

来源：`probes\_probe_config.ps1 -Path <ninfer>`

```json
metadata.name  = "huihui-qwen3.8-27b-abliterated-swift15-gsq-rco-iq2s"
provenance     = {
  "converter": "ninfer-v3",
  "recipe": "qwen3_8_27b_gguf",
  "sources": {
    "base":   { "path": "D:\\Ab1-Swift\\base" },
    "gguf":   { "path": "D:\\Ab1-Swift\\src\\huihui-swift15-iq2s-mtp.gguf" },
    "vision": { "path": "D:\\Ab1-Swift\\src\\mmproj-model-bf16.gguf" }
  },
  "ranking": "D:\\Ab1-Swift\\engine\\tools\\freq_corpus\\fixtures\\ranking\\ranking.train.counts.i64"
}
```

```json
// components.text.config
{
  "architectures": ["Qwen3_5ForCausalLM"],
  "model_type": "qwen3_5_text",
  "hidden_size": 5120,
  "vocab_size": 248320,
  "num_hidden_layers": 64,
  "max_position_embeddings": 262144,
  "tie_word_embeddings": false,
  "rms_norm_eps": 1e-06,
  "num_attention_heads": 24,
  "num_key_value_heads": 4,
  "head_dim": 256,
  "intermediate_size": 17408,
  "layer_types": [ "linear_attention","linear_attention","linear_attention","full_attention", ... 共 64 项 = 48 linear + 16 full ],
  "rope_parameters": { "rope_theta": 1e7, "partial_rotary_factor": 0.25, "mrope_section": [11,11,10] },
  "linear_num_key_heads": 16,
  "linear_key_head_dim": 128,
  "linear_num_value_heads": 48,
  "linear_value_head_dim": 128,
  "linear_conv_kernel_dim": 4
}
```

```json
// components.vision.config
{ "model_type": "qwen3_5_vision", "depth": 27, "hidden_size": 1152, "intermediate_size": 4304,
  "num_heads": 16, "patch_size": 16, "temporal_patch_size": 2, "spatial_merge_size": 2,
  "num_position_embeddings": 2304 }

// components.mtp.config
{ "architectures": ["Qwen3_5MTP"] }
```

---

## 3 上游官方 config（`https://hf-mirror.com/Qwen/Qwen3.8-27B/raw/main/config.json`）

```json
{
  "architectures": ["Qwen3_5ForConditionalGeneration"],
  "model_type": "qwen3_5",
  "transformers_version": "5.8.0.dev0",
  "text_config": {
    "model_type": "qwen3_5_text",
    "hidden_size": 5120, "num_hidden_layers": 64, "vocab_size": 248320,
    "intermediate_size": 17408, "num_attention_heads": 24, "num_key_value_heads": 4,
    "head_dim": 256, "full_attention_interval": 4,
    "linear_num_key_heads": 16, "linear_key_head_dim": 128,
    "linear_num_value_heads": 48, "linear_value_head_dim": 128,
    "linear_conv_kernel_dim": 4, "mamba_ssm_dtype": "float32",
    "mrope_section": [11, 11, 10], "rope_theta": 1e7, "partial_rotary_factor": 0.25,
    "mtp_num_hidden_layers": 1, "mtp_use_dedicated_embeddings": false,
    "attn_output_gate": true, "output_gate_type": "swish",
    "max_position_embeddings": 262144, "rms_norm_eps": 1e-06, "tie_word_embeddings": false
  },
  "vision_config": { "model_type": "qwen3_5", "depth": 27, "hidden_size": 1152,
                     "intermediate_size": 4304, "num_heads": 16, "patch_size": 16,
                     "spatial_merge_size": 2, "temporal_patch_size": 2,
                     "num_position_embeddings": 2304, "out_hidden_size": 5120 },
  "image_token_id": 248056, "video_token_id": 248057
}
```

---

## 4 逐参数比对（证明同一模型）

| 参数 | 本地 .ninfer | 官方 Qwen3.8-27B | 一致 |
|---|---|---|---|
| hidden_size | 5120 | 5120 | ✓ |
| num_hidden_layers | 64 | 64 | ✓ |
| vocab_size | 248320 | 248320 | ✓ |
| intermediate_size | 17408 | 17408 | ✓ |
| num_attention_heads | 24 | 24 | ✓ |
| num_key_value_heads | 4 | 4 | ✓ |
| head_dim | 256 | 256 | ✓ |
| layer_types 结构 | 48 linear + 16 full（4 层一循环） | `full_attention_interval 4` → 同结构 | ✓ |
| linear_num_key_heads / dim | 16 / 128 | 16 / 128 | ✓ |
| linear_num_value_heads / dim | 48 / 128 | 48 / 128 | ✓ |
| linear_conv_kernel_dim | 4 | 4 | ✓ |
| mrope_section | [11,11,10] | [11,11,10] | ✓ |
| rope_theta / partial_rotary | 1e7 / 0.25 | 1e7 / 0.25 | ✓ |
| max_position_embeddings | 262144 | 262144 | ✓ |
| rms_norm_eps | 1e-06 | 1e-06 | ✓ |
| tie_word_embeddings | false | false | ✓ |
| vision depth / hidden / inter | 27 / 1152 / 4304 | 27 / 1152 / 4304 | ✓ |
| vision patch / merge / pos_emb | 16 / 2 / 2304 | 16 / 2 / 2304 | ✓ |
| MTP | `Qwen3_5MTP` | `mtp_num_hidden_layers 1` | ✓ |
| 量化 | IQ2_S（689 个量化 tensor / 12.75 GiB） | 原始 bf16 | 差异点：量化 |

→ 本地 `.ninfer` = `Qwen/Qwen3.8-27B` 的 abliterated 版经 GSQ-RCO 流程量化成 IQ2_S，并保留 MTP 投机头与 vision 塔。

---

## 5 这条事实怎样改变方案

| 项 | 更正前（错） | 更正后（对） |
|---|---|---|
| 基座下载目标 | Qwen3.5-27B | **`Qwen/Qwen3.8-27B`** |
| transformers 要求 | ≥4.53 | **≥5.8**（官方 config 标 `5.8.0.dev0`） |
| 模态假设 | 纯文本 | **原生 VL**（text + vision tower + mmproj） |
| 微调范围 | 未界定 | 12 GB 卡上只能冻结 vision、只训 text decoder |

---

## 6 遗留不确定性（诚实标注）

1. `huihui-ai/Qwen3.8-27B-abliterated` 直取 config.json 返回 **401**（需登录），未能直接比对上游 abliterated 版与本地是否完全一致。判定依据为"参数结构全吻合 + metadata/provenance 命名一致"，属强证据但非逐字节。
2. `ninfer-v3` converter 的 recipe `qwen3_8_27b_gguf` 与 `huihui-swift15-iq2s-mtp.gguf` 的具体量化流程（GSQ-RCO 参数）无法从容器内复原，只能从命名与 `ranking.train.counts.i64` 推断其为重要性/频率引导的量化。
3. 本地容器的 `max_position_embeddings = 262144` 与官方一致；但引擎实际可用上下文由 `profiles.json` 的池参数决定（8G 长档 / 10G / 12G / 16G），二者不是同一概念，勿混用。
