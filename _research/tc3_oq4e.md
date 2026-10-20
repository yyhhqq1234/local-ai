---
license: apache-2.0
base_model: nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2
base_model_relation: quantized
library_name: mlx
pipeline_tag: text-generation
language:
  - en
tags:
  - mlx
  - omlx
  - qwen3_5
  - 4-bit
  - mtp
  - speculative-decoding
  - apple-silicon
  - coding
---

# Qwen3.8-27B Coder390 oQ4e + MTP

Coder390 (Qwen3.8-27B) quantized to oMLX oQ4e, about 4.8 bits per weight, with the multi-token-prediction (MTP) head kept for speculative decoding. Text-only, 16.33 GB, for Apple Silicon.

- Quantized from the Coder390 FP8 checkpoint with oMLX `f3ad34d2` (0.7.1.dev1), which includes the importance-weighted least-squares (LSQ) refit from [oMLX PR #4385](https://github.com/jundot/omlx/pull/4385).
- Quality is measured as KL divergence against the FP8 checkpoint on held-out code and prose. A small coding and agent test set checks that the model works in practice.
- Methods, raw data, checksums and the commands to reproduce the build are in this repository.

## Model Specifications

| | |
|---|---|
| Base model | [nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2](https://huggingface.co/nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2), `FP8/`, revision `bae2cbd736952a21006feca2630f5715016250c2` |
| Architecture | `Qwen3_5ForConditionalGeneration`, 64 layers, hidden size 5120, context length 262144 (from the base config; tested up to 16K prompt tokens) |
| Quantization | oMLX oQ4e (enhanced): 4-bit affine, group size 64; 115 modules at 5-bit, `lm_head` at 8-bit |
| Effective BPW | 4.7753 (all tensors) |
| Model size | 16.33 GB (4 safetensors shards plus config and tokenizer files) |
| MTP | Kept (29 tensors; `mtp.layers.0` down_proj and o_proj at 5-bit) |
| Modality | Text-only (no vision tensors) |
| Tested with | oMLX `f3ad34d2` (0.7.1.dev1), MLX 0.32.3, Mac Studio M4 Max 64 GB |

## Quantization Fidelity

Reference: the original Coder390 FP8 checkpoint. Held-out corpus: 16 code and 16 prose sequences, 1008 scored tokens each. KL is KL(FP8 || quantized), averaged over scored tokens.

| Corpus | Mean KL | Top-1 agreement with FP8 |
|---|---|---|
| Code (16 sequences) | 0.00957 | 97.23% |
| Prose (16 sequences) | 0.07815 | 91.11% |

- Weight level: the importance-weighted relative MSE against the FP8 weights is 0.004112 over all tensors that have importance weights.
- The KL corpus is narrow: English technical documentation and Python, ASCII only, no Chinese text.

Lower KL means the output distribution is closer to FP8. It does not mean coding accuracy or task success will be the same as FP8. Corpus construction, held-out rule, percentiles and the comparison with an earlier internal build: [docs/EVALUATION.md](docs/EVALUATION.md).

The 8-bit `lm_head` is retained to prioritize fidelity to the source FP8 checkpoint. An experimental 4-bit `lm_head` improved 16K decode throughput by 11.8% (median of six runs over two rounds; 4K: +2.9%), but increased code KL by 34.6% and failed the predefined fidelity criteria. The released checkpoint remains unchanged. Details: [docs/EVALUATION.md](docs/EVALUATION.md#experiment-4-bit-lm_head).

## Quick Start

Requires Apple Silicon and [uv](https://docs.astral.sh/uv/) (on macOS: `brew install uv`). The Hugging Face CLI `hf` comes with the `huggingface_hub` package.

Steps 2 to 6 were run end to end on oMLX `v0.7.1.dev1` in a fresh `uv` environment, using a local copy of these files (transcript in `quickstart/`). After publication, the files were downloaded with `hf download` into an empty directory without logging in (the CLI was run through `uvx`, not `uv tool install`); all checkpoint SHA-256 values matched, and steps 3 to 6 were run again on that copy.

1. Download:

   ```bash
   uv tool install huggingface_hub
   hf download tc3oliver/Qwen3.8-27B-Coder390-oQ4e-MTP-Text --local-dir ~/models/Qwen3.8-27B-Coder390-oQ4e-MTP-Text
   ```

2. Install oMLX:

   ```bash
   uv venv --python 3.12 omlx-env
   VIRTUAL_ENV=$PWD/omlx-env uv pip install "omlx @ git+https://github.com/jundot/omlx@v0.7.1.dev1"
   ```

3. Turn on MTP. Create `~/.omlx/model_settings.json`:

   ```json
   {"version": 1, "models": {"Qwen3.8-27B-Coder390-oQ4e-MTP-Text": {"mtp_enabled": true}}}
   ```

4. Start the server. The directory name under `--model-dir` is the model id:

   ```bash
   omlx-env/bin/omlx serve --model-dir ~/models --base-path ~/.omlx --port 8000
   ```

   The log shows `Lightning MTP (model_type=qwen3_5, active)` when the model loads.

5. Chat completion:

   ```bash
   curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
     "model": "Qwen3.8-27B-Coder390-oQ4e-MTP-Text",
     "messages": [{"role": "user", "content": "Write a Python function that reverses a string."}],
     "max_tokens": 256,
     "chat_template_kwargs": {"enable_thinking": false}}'
   ```

6. Tool calling:

   ```bash
   curl -s localhost:8000/v1/chat/completions -H 'Content-Type: application/json' -d '{
     "model": "Qwen3.8-27B-Coder390-oQ4e-MTP-Text",
     "messages": [{"role": "user", "content": "What is the weather in Paris?"}],
     "tools": [{"type": "function", "function": {"name": "get_weather",
       "description": "Get the current weather for a city",
       "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}}],
     "max_tokens": 512}'
   ```

   The reply has `finish_reason: tool_calls` with `get_weather` and arguments `{"city": "Paris"}`.

Notes:

- Thinking is on by default, so replies carry a `reasoning_content` field and the reasoning uses output tokens. The chat example turns it off with `"chat_template_kwargs": {"enable_thinking": false}`; the tool-calling example leaves it on. You can also set `"enable_thinking": false` for the model in `model_settings.json`. The coding and agent results below were measured with thinking off. On one test prompt both switches worked; that shows they work and says nothing about answer quality.
- Not tested: Homebrew and DMG installs of oMLX, and oMLX 0.7.0. The refit in #4385 only affects quantization, so running this model should not depend on it, but no test isolated that.

## Coding Agent Validation

Preliminary validation on a small set. 11 tasks with objective checks: 6 code (generation, bug fixing, refactoring), 1 structured JSON, 2 tool calling, 2 multi-turn agent tasks with file tools, through the oMLX OpenAI-compatible API. Thinking off, MTP off, SpecPrefill off, no prompt cache, oMLX `f3ad34d2`.

| Test | Result |
|---|---|
| Sampled (temperature 0.6, top_p 0.95, top_k 20), 8 samples per task | 77 / 88 (87.5%) |
| Greedy (temperature 0), 3 runs per task | 9 / 11 tasks |
| Pi Coding Agent, 3 small scenarios | 3 / 3 passed |

- Sampled: 8 tasks passed 8 of 8; `fix_duration_parser` 4/8, `gen_expr_eval` 3/8, `gen_merge_intervals` 6/8.
- Greedy: `fix_duration_parser` and `gen_expr_eval` failed. At temperature 0 the three runs of a task gave identical output, so this is 11 samples, not 33.
- The set is small and mostly easy, so it cannot separate small differences. It was not run on the FP8 checkpoint, so there is no FP8 baseline.
- The same tasks were also run on an earlier internal build. That comparison, including a task where the greedy results differ, is in [docs/EVALUATION.md](docs/EVALUATION.md). Task list, protocol and raw outputs: `coding/`, `results/coding/`.

### Pi Coding Agent (preliminary)

Three small scenarios, one run each, driven by the Pi Coding Agent (`@earendil-works/pi-coding-agent` 1.1.0) against a local oMLX server (`f3ad34d2`; MTP off, SpecPrefill off, thinking off, prompt cache off). A script checks the pass criteria after each run; the model's own report is not used.

| Scenario | Result | Check |
|---|---|---|
| Fix a `median` bug for even-length input | Pass | tests pass; diff touches only `stats.py` |
| Rename `fmt_price` to `format_price` across 3 files and docs | Pass | no remaining references; `cli.py` prints `tea: $4.50 $19.99`; 4 files changed |
| Two-turn change to `slugify` (second turn via `--continue`) | Pass | tests pass; `slugify("A  b!!c") == "a-bc"`; 2 tests added |

These are small Python standard-library projects. The result shows the checkpoint works in an agent loop with file tools; it is not a general agent benchmark. Sampling settings were left to the agent's and server's defaults and were not recorded. Transcripts omit the agent's system prompt (`agent/transcripts/`).

## Inference Performance

oMLX `f3ad34d2` (0.7.1.dev1), MLX 0.32.3, Mac Studio M4 Max 64 GB, MTP on, SpecPrefill off, one request at a time. Every request has a unique prefix, so the prompt is prefilled cold, and the SSD cache directory is fresh for each length. Median of three runs after one warmup. Raw data: `results/perf/new-4k-16k-spoff.json`.

| Prompt tokens | Cold prefill tok/s | TTFT | Decode tok/s | MTP acceptance | Tokens per MTP cycle |
|---|---|---|---|---|---|
| 4,101 | 259.0 | 15.83 s | 47.72 | 78.3% | 3.07 |
| 16,404 | 246.0 | 66.69 s | 40.84 | 74.4% | 2.62 |

- Peak memory over the whole server session (4K first, then 16K): 24.15 GB peak memory footprint (`/usr/bin/time -l`, includes MLX/Metal buffers), 17.88 GB maximum resident set size.
- Output length was not fixed: the model stopped on its own after 211 to 311 tokens. Each column is the median of the three runs' values. MTP parks: 0.
- One machine and one runtime version; the figures do not carry over to other hardware.

### Runtime notes

oMLX [PR #4461](https://github.com/jundot/omlx/pull/4461) fixes a dtype bug in the SpecPrefill RoPE path that left decode in float32 after a sparse prefill. It is a runtime fix, separate from the quantization (#4385) and from these weights, and it only matters when SpecPrefill is on. The table above was measured with SpecPrefill off. This checkpoint was not re-measured with SpecPrefill; the PR's measurements and conditions are in [docs/RUNTIME_NOTES.md](docs/RUNTIME_NOTES.md).

## Quantization Method & Credits

oQe records an importance matrix (imatrix) from calibration text, so that input channels carrying more signal are rounded more accurately. For each group of weights it searches for the scale and bias with the smallest importance-weighted error, then refits them by weighted least squares and keeps a refit only if it lowers that error. This happens at quantization time; the packed layout, dtype and bit allocation do not change. The MTP head is kept and the vision tower is dropped (text-only).

| | |
|---|---|
| Quantizer | oMLX `f3ad34d2fcaeb85b0469e291ab370a7f01bc8d64` (0.7.1.dev1), includes #4385 |
| MLX | 0.32.3 |
| Effective BPW | 4.7753 (quantized tensors alone: 4.7526 including scales and biases) |
| Bit distribution | 4-bit 88.72%, 5-bit 6.61%, 8-bit 4.66% of quantized parameters |
| Model size | 16.33 GB |

An earlier internal build, made with an older oMLX revision (without #4385) and MLX 0.32.2, was not released. It had higher KL against FP8 (see [docs/EVALUATION.md](docs/EVALUATION.md)). Because the oMLX revision and the MLX version both differ and no ablation holds everything else fixed, this repository does not attribute the difference to #4385 alone.

Credits:

- Original model: nerkyor (Coder390).
- Architecture and base lineage: the Qwen team. Qwen is named only to describe the architecture; this repository is not endorsed by or affiliated with the Qwen team.
- oQe quantization and the LSQ refit: jundot and the [oMLX](https://github.com/jundot/omlx) contributors ([PR #4385](https://github.com/jundot/omlx/pull/4385)). The refit is their work, not an algorithm developed here.
- Independent quantization, validation and packaging: [tc3oliver](https://github.com/tc3oliver).

## Reproducibility

| | |
|---|---|
| Source | `nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2`, `FP8/`, revision `bae2cbd736952a21006feca2630f5715016250c2`. SHA-256 of its 10 weight files: [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md); they match the Hugging Face file hashes for that revision. |
| Quantizer | oMLX `f3ad34d2fcaeb85b0469e291ab370a7f01bc8d64`, MLX 0.32.3, mlx-lm 0.31.4.dev132+g94cdcae13, mlx-vlm 0.7.7, Python 3.13.15 |
| Settings | oQ4, group size 64, enhanced, preserve MTP, text-only, bfloat16, no bpw target (`tools/run_quant_v2.py`) |
| Calibration | oMLX built-in `oqe_code_multilingual` set, 128 samples x 512 tokens, fixed sampling seed. The text is part of oMLX and is not redistributed. |
| Importance matrix | `reproducibility/imatrix/` (12,338,751 bytes, SHA-256 `1ab5d7ddbe5f58c8e6fa37d17d0bf4ecf22b9ffb9c8943e5f9327fb896e7546f`). It was collected in an earlier run and reused for this build. oMLX only accepts the cache for the same source files, so `tools/set_source_mtimes.py` first checks the SHA-256 of every source file and changes modification times only if all of them match. |
| Checksums | SHA-256 of every checkpoint file as produced: `results/sha256_coder390-oQ4e-mtp-v2.txt`. One report file with a local path is listed there but not distributed (`results/README.md`). |
| Quantization log | `results/quantization_run_excerpt.txt`: 503 weighted LSQ refit calls, 488 s, 1876 output tensors |
| Evaluation | `tools/`, `coding/`, `agent/` and `results/`; every number is traced to a raw file in `claims_ledger.md` |

Rebuilding the importance matrix from scratch may give a different one. Reusing the distributed cache end to end on a fresh download of the source was not tested. Details: [docs/REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).

## Known Limitations

- Text-only: no image or video input.
- The coding set is small (11 tasks, mostly easy) and has no FP8 baseline. The Pi agent check is three small scenarios, not a general agent benchmark. Thinking-on behavior was not tested.
- KL against FP8 measures distribution closeness. It does not predict coding accuracy or task success, and the KL corpus is narrow (see above).
- Serving and MTP were verified only with oMLX on one Apple Silicon machine (M4 Max, 64 GB). The KL evaluation used mlx-lm for plain forward passes. Other runtimes, other hardware and other oMLX versions were not tested.
- SpecPrefill: the performance figures are for SpecPrefill off. Without the fix in #4461, SpecPrefill-on decode was measured at roughly half the speed on three Qwen3.5-family checkpoints, including an earlier build of this model ([docs/RUNTIME_NOTES.md](docs/RUNTIME_NOTES.md)). This checkpoint was not measured with SpecPrefill.
- Sampling parameters were sent with every request, but whether the server applied them was checked only indirectly, through the variety of outputs.
- The source repository is tagged `uncensored`, its training base name also contains "Uncensored", and its README gives no safety evaluation. This quantized version has not been evaluated for safety or refusal behavior, and its responses to sensitive requests may differ from those of the official Qwen models. Evaluate it for your use case and use it responsibly.
- The license is the Apache-2.0 declared by the source authors. Rights to the source model's third-party training data cannot be verified here, and nothing in this repository is a legal guarantee.

## License & Attribution

This repository keeps the Apache-2.0 license that the source and base authors state for their work. It is a modified version of the source (quantized, text-only). The license text is in `LICENSE` and the attribution and modification notice is in `NOTICE`. Training data and its licensing information are described in the [source repository](https://huggingface.co/nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2).
