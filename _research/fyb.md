---
license: other
license_name: swift-open-license-1.0
library_name: ninfer
pipeline_tag: image-text-to-text
inference: false
base_model:
  - ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF
base_model_relation: quantized
language:
  - en
  - zh
tags:
  - ninfer
  - iq2_s
  - iq2s_mtp
  - iq2_xs
  - iq3_xxs
  - iq3_s
  - gguf-blocks
  - qwen3.8
  - mtp
  - speculative-decoding
  - swift
  - multimodal
  - image-text-to-text
---

# Swift-1.5 Qwen3.8-27B · GSQ-RCO — NInfer

Swift-1.5 Qwen3.8-27B is [UkisAI's Swift 1.5 fine-tune](https://huggingface.co/ukisai/Swift-1.5-Qwen3.8-27B-GSQ-RCO-GGUF)
of Qwen3.8-27B, quantized by UkisAI as the **GSQ-RCO** GGUF series
(mixed-precision per-tensor allocation, optional MTP-head package).

This repository repackages that GGUF series into single-file **`.ninfer`** containers
for the NInfer engine. Four tiers are published, all built from the `-mtp` GGUF packages:

| Tier | File | Size | Weights | Bit budget |
|---|---|---:|---:|---:|
| **IQ2_XS** | `swift15_iq2xs_mtp.ninfer` | 8.77 GiB | 8.34 GiB | smallest |
| **IQ2_S** | `swift15_iq2s_mtp.ninfer` | 9.55 GiB | 8.63 GiB | small |
| **IQ3_XXS** | `swift15_iq3xxs_mtp.ninfer` | 10.33 GiB | 9.94 GiB | balanced |
| **IQ3_S** | `swift15_iq3s_mtp.ninfer` | 11.91 GiB | 11.50 GiB | highest fidelity |

Pick by weight budget: **IQ2_XS** when VRAM is tightest, **IQ3_S** when fidelity matters
most. Note the IQ3_S tier is ~11.9 GiB of weights plus KV cache, so it needs a 16 GB+
card or offloading — the three smaller tiers fit smaller cards. All four carry the
identical component set — only the source GGUF's per-tensor quantization allocation differs.

**Format conversion only.** Tensor payloads are imported verbatim from the source
GGUF blocks (`gguf_blocks_v1` layout — `gguf_iq2_s`, `gguf_iq2_xxs`, `gguf_iq2_xs`,
`gguf_iq3_s`, `gguf_iq3_xxs`, `gguf_iq1_s`, `gguf_iq1_m`, `gguf_q2_k`, `gguf_q4_k`,
`gguf_q6_k`, `gguf_iq4_xs`); vision tensors are re-encoded groupwise
(`q4/q5_g64_fp16`, `q8_g32_fp16`) from the BF16 mmproj. No re-quantization of the
text tower, no retraining.

## Files

| File | Size | SHA-256 |
|---|---:|---|
| `swift15_iq2xs_mtp.ninfer` | 9,420,962,560 B | `aee68debfecb…d34e84` |
| `swift15_iq2s_mtp.ninfer` | 10,257,632,000 B | `2df7259e93cb…82045e` |
| `swift15_iq3xxs_mtp.ninfer` | 11,092,478,720 B | `2c42cf6f9e7c…09c211` |
| `swift15_iq3s_mtp.ninfer` | 12,790,639,360 B | `0e1771e4df42…4c0816` |
| `swift15_iq2xs_mtp.ninfer.conversion.json` | 505,290 B | `814550555a3f…53c1f47` |
| `swift15_iq2s_mtp.ninfer.conversion.json` | 503,627 B | `2a49e9bcb879…8adfedc` |
| `swift15_iq3xxs_mtp.ninfer.conversion.json` | 504,432 B | `2434dda97888…afa098` |
| `swift15_iq3s_mtp.ninfer.conversion.json` | 500,726 B | `32f5aa00be1e…438882` |

Full digests are in `SHA256SUMS`.

Each `.ninfer` is one complete container: text tower (64 layers, 4:1 linear/full
attention mix), vision tower, MTP head, proposal head, tokenizer, chat template and
media-processor resources. No separate adapter or patch files needed. The identical
`LICENSE`, `NOTICE` and `LICENSE-APACHE-2.0` cover all four tiers.

## Engine

Needs a NInfer engine build that reads the `gguf_blocks_v1` container layout.
This is a different dialect from the ternary `PQ2_0_G128` / `PTQ1_0_G128`
artifacts — the two are **not** interchangeable.

Converted with the `qwen3_8_27b_gguf` recipe from
[Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco](https://github.com/Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco)
(Apache-2.0, forked from [iamwavecut/ninfer-all](https://github.com/iamwavecut/ninfer-all)).

## Provenance

```
Qwen3.8-27B (base)                Qwen/Qwen3.8-27B                 Apache-2.0
Swift 1.5 fine-tune + GSQ-RCO     ukisai/Swift-1.5-Qwen3.8-27B-…   Swift Open License v1.0
  GGUF quantization (all four tiers, -mtp packages)
This repo                         .ninfer repackaging (format conversion only)
```

The weight source is licensed under the **Swift Open License v1.0** (NOTICE included),
which permits redistribution with attribution; commercial use beyond the
USD-1-million revenue threshold requires a separate arrangement with UkisAI.
The Base Model remains Apache-2.0 (copy included as `LICENSE-APACHE-2.0`).

## Verification

The `*.conversion.json` files record every object for their tier: source tensor,
method (`import_encoded` / `cast_direct` / `grouped_absmax`), format and layout —
1186 tensors + 6 resources (IQ2_S), 1192 + 6 (IQ2_XS), 1189 + 6 (IQ3_XXS) and
1177 + 6 (IQ3_S), matching each source GGUF inventory. `SHA256SUMS` covers all
eight files.

> **File naming:** all four tiers carry the MTP head and are named `<tier>_mtp`
> accordingly; `swift15_iq2s_mtp.ninfer` was renamed from `swift15_iq2_s.ninfer`
> on 2026-10-03 for consistency. The bytes are unchanged
> (SHA-256 `2df7259e93cb…82045e`); only the file name and its references moved.

## Intended use

Research and local inference. Not validated for production or safety-critical use.

[中文说明](README_zh.md)
