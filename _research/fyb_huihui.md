---
license: apache-2.0
library_name: ninfer
pipeline_tag: image-text-to-text
inference: false
base_model:
  - huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF
base_model_relation: quantized
language:
  - en
  - zh
tags:
  - ninfer
  - abliterated
  - uncensored
  - iq2_xs
  - gguf-blocks
  - qwen3.8
  - mtp
  - speculative-decoding
  - swift
  - multimodal
  - image-text-to-text
---

# Huihui Qwen3.8-27B Abliterated · Swift-1.5 GSQ-RCO — NInfer

Format repackaging of [huihui-ai's abliterated Swift-1.5 GSQ-RCO GGUF series](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF)
into single-file **`.ninfer`** containers for the NInfer engine.

**The abliteration is not ours.** The refusal-direction ablation was performed by
huihui-ai on the Swift-1.5 tiers of that GGUF repository; this repository only
repackages their GGUF blocks into the NInfer container format. See
[Attribution](#attribution) and the usage warnings carried over below.

Tiers are published one at a time; this repository grows as each conversion completes.
**All four tiers are now published.**

**Hugging Face only.** These artifacts are not mirrored on ModelScope: that platform's
repository-name review rejects the word *Abliterated*, and the model card's usage
warnings make it a poor fit for that audience anyway.

Note the IQ3_S tier is ~11.9 GiB of weights, so it needs a 16 GB+ card or offloading;
the three smaller tiers fit smaller cards.

| Tier | File | Size | Weights | Status |
|---|---|---:|---:|---|
| **IQ2_XS** | `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_XS-mtp.ninfer` | 8.76 GiB | 8.34 GiB | published |
| **IQ2_S** | `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer` | 9.55 GiB | 8.63 GiB | published |
| **IQ3_XXS** | `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_XXS-mtp.ninfer` | 10.33 GiB | 9.94 GiB | published |
| **IQ3_S** | `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_S-mtp.ninfer` | 11.91 GiB | 11.50 GiB | published |

**Format conversion only.** Tensor payloads are imported verbatim from the source
GGUF blocks (`gguf_blocks_v1` layout — `gguf_iq1_m`, `gguf_iq1_s`, `gguf_iq2_s`,
`gguf_iq2_xs`, `gguf_iq2_xxs`, `gguf_iq3_s`, `gguf_iq3_xxs`, `gguf_iq4_xs`,
`gguf_q2_k`, `gguf_q4_k`, `gguf_q6_k`); vision tensors are re-encoded groupwise
(`q4/q5_g64_fp16`, `q8_g32_fp16`) from the BF16 mmproj. No re-quantization of the
text tower, no retraining, no additional ablation.

## Files

| File | Size | SHA-256 |
|---|---:|---|
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_XS-mtp.ninfer` | 9,411,869,440 B | `fa90cddbfa91…93bca8` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer` | 10,257,632,000 B | `85bfa2224894…9e55dd` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_XXS-mtp.ninfer` | 11,092,478,720 B | `2a9b986db19f…2ed483` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_S-mtp.ninfer` | 12,790,639,360 B | `ab8a06eaf805…f1d643` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_XS-mtp.ninfer.conversion.json` | 499,518 B | `d6d524a6e89c…d9788fa` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer.conversion.json` | 497,860 B | `defd3cc3f490…a5a0310` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_XXS-mtp.ninfer.conversion.json` | 498,653 B | `ff3879a7f78d…0aa2e022` |
| `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ3_S-mtp.ninfer.conversion.json` | 494,951 B | `85f4b78fd0e2…b662cc9` |

Full digests are in `SHA256SUMS`.

Each `.ninfer` is one complete container: text tower (64 layers, 4:1 linear/full
attention mix), vision tower, MTP head, proposal head, tokenizer, chat template and
media-processor resources. No separate adapter or patch files needed.

## Engine

Needs a NInfer engine build that reads the `gguf_blocks_v1` container layout
(this is a different dialect from the ternary `PQ2_0_G128` / `PTQ1_0_G128`
artifacts — the two are **not** interchangeable).

Converted with the `qwen3_8_27b_gguf` recipe from
[Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco](https://github.com/Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco)
(Apache-2.0, forked from [iamwavecut/ninfer-all](https://github.com/iamwavecut/ninfer-all)).

## Attribution

```
Qwen3.8-27B (base)                  Qwen/Qwen3.8-27B                     Apache-2.0
Swift 1.5 fine-tune + GSQ-RCO       ukisai/Swift-1.5-Qwen3.8-27B-…       Swift Open License v1.0
  GGUF quantization (IQ2_XS tier)
Abliteration (layers 22–52)         huihui-ai/Huihui-Qwen3.8-…-GGUF      Apache-2.0
This repo                           .ninfer repackaging (format conversion only)
```

The abliteration step is huihui-ai's work, applied to layers 22–52 (0-based);
MTP and the vision tower were left unmodified by them. The upstream Swift
contribution is licensed under the **Swift Open License v1.0**, which permits
redistribution with attribution. See `NOTICE` for the full chain.

## Usage warnings (carried over from the abliterated source)

The source model's safety filtering has been significantly reduced. Outputs may be
sensitive, controversial or inappropriate. Not suitable for public-facing settings,
for use by minors, or for applications requiring high safety. Users are solely
responsible for compliance with applicable law and for reviewing generated output.
Recommended for research, testing and controlled environments only.

## Verification

`Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-*.ninfer.conversion.json` records every object: source
tensor, method (`import_encoded` / `cast_direct` / `grouped_absmax`), format and
layout — 1177–1192 tensors + 6 resources per tier, matching the source GGUF
inventory.
The source GGUF's SHA-256 was verified against huihui-ai's LFS digest before
conversion. `SHA256SUMS` covers every published file.

## Intended use

Research and local inference. Not validated for production or safety-critical use.

[中文说明](README_zh.md)
