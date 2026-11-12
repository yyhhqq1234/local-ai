# Upstream Issue 草稿 · NInfer 不支持 Qwen3.5-9B（H=4096）

> 目标仓库：https://github.com/Neroued/ninfer
> 整理时间：2026-11-07
> 提交前请先核对：仓库是否已有同类 issue、版本号是否仍为当前最新

---

## Title

`unsupported logical projection geometry` when loading a Qwen3.5-9B (H=4096) artifact

## Body

### Summary

A Qwen3.5 Dense model with `hidden_size=4096` converts successfully to a v3 artifact
(weights load at 5.03 GiB/s) but the engine refuses to start:

```
ERROR startup failed | initializing frontend | 60.5 ms
FATAL server failed during startup
  | text/layers/0: input projection: unsupported logical projection geometry
```

Reading `docs/maintainer/qwen3_5-model.md` L53-83, `execution remains bounded by implemented Ops`
and `the current fused input projections have explicit Dense/MoE shapes`, and the documented
geometries are only:

| Quantity | 27B Dense | 35B-A3B MoE |
|---|---:|---:|
| Hidden width H | 5120 | 2048 |
| GDN key heads / value heads | 16 / 48 | 16 / 32 |
| GDN head dim | 128 / 128 | 128 / 128 |

Our model has `H=4096`, `GDN 16/32 heads`, `head_dim 128/128` — i.e. every GDN quantity matches
the 35B-A3B row except `H`. So the rejection looks like the fused input projection shape table
being keyed on `H ∈ {5120, 2048}` only.

**Question:** is `H=4096` intentionally unsupported, or is it a gap that could be added?

### Reproduction

**Model config (relevant fields)**

```json
{
  "model_type": "qwen3_5_text",
  "hidden_size": 4096,
  "num_hidden_layers": 32,
  "num_attention_heads": 16,
  "num_key_value_heads": 4,
  "head_dim": 256,
  "intermediate_size": 12288,
  "linear_num_key_heads": 16,
  "linear_key_head_dim": 128,
  "linear_num_value_heads": 32,
  "linear_value_head_dim": 128,
  "linear_conv_kernel_dim": 4,
  "layer_types": ["linear_attention","linear_attention","linear_attention","full_attention", "..."],
  "full_attention_interval": 4,
  "vocab_size": 248320,
  "rms_norm_eps": 1e-6,
  "rope_parameters": { "rope_theta": 10000000.0, "partial_rotary_factor": 0.25,
                       "mrope_section": [11, 11, 10] }
}
```

**Conversion**

```bash
python -m tools.convert \
  --model <hf_dir> --recipe qwen3_5_9b \
  --components text --device cpu --rows-per-chunk 512 \
  --name oxcoder-9b --out model.ninfer
```

Conversion completes: `391 objects, 1 files`, formats
`{bf16: 177, fp32: 48, q4_g64_fp16: 64, q5_g64_fp16: 96, q8_g32_fp16: 2}`,
layouts `{contiguous_le_v1: 225, row_split_k128_v1: 162}`.

**Engine load**

```bash
ninfer-serve.exe model.ninfer --max-context 8192 --prefill-chunk 128
```

```
INFO  loading weights | 6.03 GiB
INFO  weights ready | 6.03 GiB | 1.2s | 5.03 GiB/s
ERROR startup failed | initializing frontend | 60.5 ms
FATAL server failed during startup
  | text/layers/0: input projection: unsupported logical projection geometry
```

Engine build: `v0.6.0-rtx3090-1215-gad64e4e1-dirty`
Device: RTX 5070 Ti Laptop (sm_120), 12 GB

### What we already ruled out

We spent several hours checking each candidate cause; all of these are **not** the problem:

| Hypothesis | Evidence it is not the cause |
|---|---|
| Bad quantization | Weights load fully at 5.03 GiB/s; failure is in the frontend after weight upload |
| GDN tensors wrongly merged | `docs/maintainer/weight-conversion.md` says Q/K→Q4 parent and gate/V→Q5 parent is by design. We also forced the four GDN projections into separate objects (different formats, 96 projections) and got the **identical** error |
| Wrong GDN shapes in the artifact | `gdn/query` and `gdn/key` are both `(2048, 4096)` as `load/text.cpp` expects (`k=2048`, `h=4096`) |
| Missing MTP component | `--components text` is the documented starting point; error is not about a missing component |
| Wrong engine flags | All five of these produce the identical error: `--device-profile off`, `--no-prefill-cublas-projections`, `--no-cuda-graph`, `--gdn-state-fp16`, `--no-prefill-a8` |

### What we would need

Either:

1. **A definitive statement** that `H=4096` is unsupported, so we can stop pursuing this path; or
2. If it is a gap: which Ops have the `H` baked in? We would like to know whether it is:
   - only the fused input projection shape table (addable), or
   - also the GDN kernel's shared-memory sizing / tile layout (a real kernel change)

The second distinction decides whether a patch is viable or would only convert a clean startup
failure into a silent runtime error, so any pointer to the relevant source location would help.

### Context

This is a locally fine-tuned derivative of `OrionLLM/OxCoder-9B`
(base `Qwen/Qwen3.5-9B`, 32 layers, 24 GDN + 8 full-attention). The same weights export to GGUF and
run under a Qwen3.5-capable llama.cpp build at 9 tok/s, so the checkpoint itself is fine — the
difference is purely in engine support.

---

## 提交前检查清单

- [ ] 仓库无同类 open issue（搜 `unsupported logical projection geometry`、`qwen3.5 9B`）
- [ ] 版本号 `v0.6.0-rtx3090-1215-gad64e4e1-dirty` 仍为当前版本（若已更新，先升级再复现）
- [ ] 附上 `ninfer-all-master/docs/maintainer/qwen3_5-model.md` 对应的行号引用（L53-83）
- [ ] 不要附带模型权重；config.json 片段已足够
- [ ] 若是私有部署环境，脱敏 `-dirty` 相关细节

---

## 附录：从 vendored 源码里找到的直接证据（提交时请一并附上）

> 注意：本地 vendored 源码的版本与运行中的 exe 不完全一致
> （源码里没有 `unsupported logical projection geometry` 这个确切字符串），
> 所以以下是**同构证据**，不是同一份代码。请在提交前用你们当前 master 复核这几处。

### 证据 1：GDN kernel 按几何硬编码成独立 .cu

```text
src/ops/linear_attention/gated_delta_net/control/bf16/
  launch.h
  n64_k2048.cu      ← H=2048（35B-A3B）
  n96_k2560.cu
  n96_k5120.cu      ← H=5120（27B）
```

**没有 k4096 对应的 .cu 文件。**

### 证据 2：launcher 只声明了三档

```cpp
// launch.h
void launch_n96_k5120(const Inputs&, GdnControlOutputs, Plan, Scratch, CudaExecutionView);
void launch_n64_k2048(const Inputs&, GdnControlOutputs, Plan, Scratch, CudaExecutionView);
void launch_n96_k2560(const Inputs&, GdnControlOutputs, Plan, Scratch, CudaExecutionView);
```

### 证据 3：找不到 launcher 就抛错

```cpp
// execute.cpp:34
throw std::logic_error("gdn_control: missing geometry launcher");
```

### 证据 4：binding 层没有 H 白名单（说明校验确实在 Op 层）

```cpp
// src/models/qwen3_5/load/text.cpp:35-55  bind_gdn()
const auto h = text.hidden_size;      // 动态，无硬编码
const auto k = g.key_width();
const auto v = g.value_width();
out.query = b.parameter(p + "gdn/query", {k, h}, {p + "mixer_input"});
out.key   = b.parameter(p + "gdn/key",   {k, h}, {p + "mixer_input"});
out.value = b.parameter(p + "gdn/value", {v, h}, {p + "mixer_input"});
out.z     = b.parameter(p + "gdn/z",     {v, h}, {p + "mixer_input"});
```

### 因此我们想知道的是

1. 加 H=4096 支持，是**新增一个 `n?_k4096.cu` kernel**（需要按你们的 tile/shared-memory 模板重写并调优），
   还是只需扩一个形状表？
2. 如果 `n96_k5120` 这个 kernel 的模板是参数化的（n 与 k 只影响编译期常量），
   那么 `n96_k4096` 或 `n64_k4096` 是否能直接由模板实例化得到？还是要重新定 tile 大小？
3. 官方对 `n` 的取值规律是什么？（27B 与 35B-A3B 都是 n96 / n64 与 value heads 48/32 的组合）
   我们的是 value heads = 32、key heads = 16、head_dim = 128、H = 4096。

如果有模板化路径，我们愿意自己提 PR；如果需要重写 kernel，我们会评估是否等官方支持。

---

## 附录二：9B 缺失的投影形状清单（可直接照此补 kernel）

`src/ops/linear/projection/bf16/bf16_shapes.h` 当前声明 21 个形状，k 只有
`320 / 1152 / 1536 / 2560 / 4304 / 4608 / 5120 / 6144 / 10240`。

Qwen3.5-9B（H=4096）需要的形状**全部缺失**：

| 用途 | 形状 (n, k) | 来源张量 |
|---|---|---|
| vocab 嵌入 / 输出头 | **248320 × 4096** | `embed_tokens` / `lm_head` |
| GDN in_proj_qkv | **8192 × 4096** | `linear_attn.in_proj_qkv.weight` |
| GDN in_proj_z | **4096 × 4096** | `linear_attn.in_proj_z.weight` |
| GDN out_proj | **4096 × 4096** | `linear_attn.out_proj.weight` |
| 全注意力 q_proj | **8192 × 4096** | `self_attn.q_proj.weight` |
| 全注意力 k/v_proj | **1024 × 4096** | `self_attn.k_proj.weight` / `v_proj.weight` |
| 全注意力 o_proj | **4096 × 4096** | `self_attn.o_proj.weight` |
| MLP gate / up | **12288 × 4096** | `mlp.gate_proj.weight` / `up_proj.weight` |
| MLP down | **4096 × 12288** | `mlp.down_proj.weight` |

去重后需要的新形状：

```text
n248320_k4096
n12288_k4096
n8192_k4096
n4096_k4096
n1024_k4096
n4096_k12288
```

**6 个新形状。** 若 `MmaGeometry<N,K,?>` 与现有 `n64_k2048.cu` / `n96_k5120.cu` 的模板
签名兼容，则每个文件只需照抄并改模板参数，代码量很小（`n64_k2048.cu` 全文件仅 45 行）。

### 此外请确认 GDN recurrent kernel

`gated_delta_net/control/bf16/` 只有三档：
```text
n64_k2048.cu    n96_k2560.cu    n96_k5120.cu
```

9B 的 GDN 内部几何是 **k=2048 / v=4096 / 16 key heads / 32 value heads / head_dim 128**，
这与 35B-A3B **完全相同**（`MmaGeometry<32, 2048, 64>`），只有外层 hidden H 不同。
所以 `n64_k2048` 这一档是否可直接复用，是本 issue 第 2 个问题：

> GDN recurrent 部分是否与 H 无关？如果无关，那 9B 只缺外面的 6 个投影形状；
> 如果有关，GDN 也需要新增一档。

### 我们这边的环境状况（说明为什么希望上游处理）

```text
运行侧：RTX 5070 Ti Laptop 12 GB（sm_120），引擎 build v0.6.0-rtx3090-1215-gad64e4e1-dirty
编译侧：本机没有 nvcc / cmake / MSVC，且 vendored 源码与运行中的 exe 版本不一致
⇒ 无法自行编译验证，只能提交此报告
```
