---
license: apache-2.0
base_model: 0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored
pipeline_tag: text-generation
library_name: gguf
tags:
- gguf
- llama.cpp
- qwen3.8
- abliterated
- uncensored
- gsq
- rco
- non-uniform
- mixed-precision
- imatrix
- mtp
---

# Qwen3.8-27B-Heretic · GSQ-RCO GGUFs

**Non-uniform GGUF quantizations** of **[RVN Qwen3.8-27B-Heretic-Abliterated-Uncensored](https://huggingface.co/0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF)** (refusals 0-1/100, KL ~ 0.0085 vs base). Instead of one uniform quantization type for all tensors, **each of the 851 tensors carries its own type**, following the per-tensor **RCO allocation** published by IST-DASLab for their [GSQ-RCO release of Qwen3.8-27B](https://huggingface.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF), quantized locally with **llama.cpp** and the **official importance matrix** `imatrix-qwen3.8-27b.gguf`. Files are standard GGUF and run unmodified in llama.cpp / Ollama / LM Studio.

## Why this release exists

This family was made at the request of community member **[Heidagger44](https://huggingface.co/Heidagger44)** in [discussion #11](https://huggingface.co/0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF/discussions/11):

> Regarding IQ3_S there is new method: GSQ-RCO, if it's possible to combine your abliteration method with this quantization, we would have a true refusal free Qwen3.8-27B running fully on 16GB cards.

Thanks for the pointer - this is that combination, in four sizes.

## Available files

| File | Target bpw | Weights | Notes |
|---|---:|---:|---|
| `RVN-Qwen3.8-27B-Heretic-GSQ-RCO-IQ2_XS.gguf` | 2.50 | 8.45 GB | Smallest tier - 12 GB-class cards |
| `RVN-Qwen3.8-27B-Heretic-GSQ-RCO-IQ2_S.gguf` | 2.75 | 9.28 GB | Balanced low-memory tier |
| `RVN-Qwen3.8-27B-Heretic-GSQ-RCO-IQ3_XXS.gguf` | 3.00 | 10.12 GB | Strong sub-10.5 GB operating point |
| `RVN-Qwen3.8-27B-Heretic-GSQ-RCO-IQ3_S.gguf` | 3.50 | 11.80 GB | **Recommended on 16 GB cards** |
| 4 x `*-mtp.gguf` twins | - | +0.42 GiB each | Embedded official Qwen3.8 MTP/NextN head; main weights identical |

## Quality - measured, not assumed

Perplexity on wikitext-2 (`llama-perplexity`, ctx 4096, one RTX PRO 6000 Blackwell, full offload):

| Variant | PPL (wikitext-2) | Delta vs F16 |
|---|---:|---:|
| F16 reference (`RVN-F16.gguf`) | 6.1197 | - |
| **GSQ-RCO IQ3_S** | **6.1778** | **+0.95%** |
| GSQ-RCO IQ3_XXS | 6.3486 | +3.7% |
| GSQ-RCO IQ2_S | 6.5058 | +6.3% |
| GSQ-RCO IQ2_XS | 6.7724 | +10.7% |
| *A/B:* uniform `RVN-IQ3_S.gguf` | 6.2956 | +2.9% |

At **3.50 bpw the allocation lands within 1% of F16** - and a same-class uniform quantization sits 1.9% behind it **at a larger file size** (12.42 GB vs 11.80 GB). Generation speeds (same box, full offload): IQ2_XS 105 t/s, IQ2_S 101 t/s, IQ3_XXS 97 t/s, IQ3_S 90 t/s, **IQ3_S-mtp 150 t/s** with `--spec-type draft-mtp`.

## How these files were built

1. **Allocation** - IST-DASLab's published per-tensor RCO maps for this tier set (851 tensor-to-type entries each; targets 2.50-3.50 bpw).
2. **Quantization** - every tensor of `RVN-F16.gguf` quantized at its assigned type with `llama.cpp` (`--tensor-type-file`), using the official `imatrix-qwen3.8-27b.gguf`.
3. **MTP embedding** - the official Qwen3.8 MTP/NextN head (from `mtp-RVN.gguf`) raw-byte merged into the `-mtp` twins (`block_count=65`, `nextn_predict_layers=1`).

**Exactness** - header audit per file: 803/851 tensors match the published allocation exactly; the 48 `ssm_alpha` tensors are held at F32 by llama.cpp's SSM precision rule (the map lists BF16 - strictly higher precision, ~ +24 MB/file).

**Provenance note** - this reproduces the RCO **allocation** with optimized local quantization. The per-tensor GSQ *refinement* pass from ISTA's internal pipeline is not reproduced; its current public implementation is a research checkpoint that regresses end-to-end KL in its own tests. The allocation and the official importance matrix are the published, verifiable ingredients. If the KL-gated refinement lands upstream we will re-run it.

## Usage

```bash
# 16 GB cards: start here
llama-cli -m RVN-Qwen3.8-27B-Heretic-GSQ-RCO-IQ3_S.gguf -ngl 99 --temp 1.0 -p "Your prompt"

# speculative decoding with the embedded MTP head (llama.cpp >= b10440):
llama-cli -m RVN-Qwen3.8-27B-Heretic-GSQ-RCO-IQ3_S-mtp.gguf -ngl 99 \
  --spec-type draft-mtp --spec-draft-n-max 2 --parallel 1 -p "Your prompt"
```

Thinking mode follows the model's chat template. A **vLLM/Transformers (compressed-tensors) GSQ variant** lives in the companion repository under [`GSQ-3bit/`](https://huggingface.co/0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored/tree/main/GSQ-3bit).

## Related repositories

- Main model + standard quant spectrum: [Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF](https://huggingface.co/0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored-GGUF)
- FP16 safetensors (vLLM/SGLang): [Qwen3.8-27B-Heretic-Abliterated-Uncensored](https://huggingface.co/0bserverx/Qwen3.8-27B-Heretic-Abliterated-Uncensored)

## Credits

Per-tensor RCO allocation + official importance matrix: [IST-DASLab](https://huggingface.co/ISTA-DASLab) (GSQ-RCO release). Quantization, verification, and MTP embedding: this repository. Base abliteration (RVN / ARA): see the main repository.
