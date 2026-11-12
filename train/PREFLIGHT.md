# OXCODER-9B 后训练 · 开工前准备与坑预警

> 状态：**未开训**。本文件只做准备工作、优化与风险预警，不触发训练。
> 生成时间：2026-10-28 · 对应计划：[PLAN-OXCODER-POSTTRAIN.md](../PLAN-OXCODER-POSTTRAIN.md)
> 读完这份就能直接开工，不需要再翻历史对话。

---

## 0 一句话现状

数据、环境、脚本全部就绪；ctx 决策已用真实 tokenizer 实测敲定为 **9216（零切分零膨胀）**；
剩余 3 个**必须先解决**的接入问题：`assistant_only_loss` 标记缺失、`fla` 未装（速度瓶颈）、
引擎未停会抢显存。解决后即可开训。

---

## 1 阶段状态（对照 PLAN 的 P0–P6）

| 阶段 | 内容 | 状态 | 说明 |
|---|---|---|---|
| **P0** | 环境准备 | ✅ **完成** | triton-windows + liger-kernel 已装；LigerSFTTrainer 手写接入；3 个显存/内存坑已修 |
| **P1** | 去审查确认 | ✅ **完成** | `train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0` 已产出 |
| **P2** | 主训练（2A/2B/2C） | ⬜ **未开始** | **当前卡在 P2 前置：ctx 决策 + 数据形态**（本文件解决的就是这块） |
| **P3** | merge + 冒烟 | ⬜ 未开始 | 依赖 P2 |
| **P4** | MTP 后训练 | ⬜ 未开始 | MTP 权重已落盘（464 MB），脚本已就绪 |
| **P5** | GSQ 量化 + 部署 | ⬜ 未开始 | 配方已注册，`.ninfer` 已产出一版（5.83 GiB） |
| **P6** | 六探针 + 四层对齐 | ⬜ 未开始 | 阈值已定 |

**当前精确位置**：P2 的「数据形态决策」子步骤，已完成 90%（ctx 实测 + 切分脚本 + 全量审计），
差最后一步「按 9216 生成三份训练集」。

---

## 2 ctx 决策（已实测敲定）

### 2.1 为什么不能盲目用 2048 或 4096

轨迹样本的**提示词底噪**（system+user）本身就很大：

| 数据集 | system | user | **sys+user（底噪）** | assistant |
|---|---|---|---|---|
| Nemotron swe-8k | 1694 | 1274 | **2968** | 5233 |
| Nemotron swe-16k | 1694 | 1273 | **2967** | 13426 |
| deepswe-8k | 12 | 1169 | **1181** | 7020 |
| rebench-8k | 46 | 464 | **553** | 7679 |

→ ctx 2048 时 Nemotron 连提示词都装不下，**必然截断**。

### 2.2 各 ctx 档实测结果（真实 tokenizer，字符覆盖全部 1.000000）

| 数据集 | 原行 | ctx 4096 | ctx 6144 | ctx 8192 | **ctx 9216** | ctx 10240 |
|---|---|---|---|---|---|---|
| swe-8k | 1500 | 15099 (×3.479) | 3299 (×1.329) | 3000 (×1.269) | **1500 (×1.000)** | 1500 (×1.000) |
| swe-16k | 500 | 12995 (×4.423) | 3000 (×1.684) | 1686 (×1.325) | 1502 (×1.273) | 1273 (×1.211) |
| deepswe | 113 | 424 (×1.206) | 233 (×1.076) | 226 (×1.069) | **113 (×1.000)** | 113 (×1.000) |
| rebench | 150 | 478 (×1.163) | 302 (×1.076) | 300 (×1.070) | **150 (×1.000)** | 150 (×1.000) |
| **轨迹合计** | 2263 | ×3.60 | ×1.48 | ×1.27 | **×1.099** | ×1.07 |
| kitty core | 5602 | ×1.000 | ×1.000 | ×1.000 | **×1.000** | ×1.000 |
| nsfw 全部 | 13668 | ×1.000 | ×1.000 | ×1.000 | **×1.000** | ×1.000 |

**结论：硬件硬上限是 ctx 4096（2026-10-28 全量实测定案）。**

> ⚠️ 早期基于显存估算以为 9216 可行，**已被实测推翻**。见 §2.3 的实测单步耗时：
> ctx 8192 单步 1149 s（reserved 25.98 GiB 远超物理 11.91 GiB，Windows WDDM 换页），
> ctx 9216 直接 OOM。**只有 ctx 4096 能跑（26.9 s/步，稳态 15.1 s）。**

### 2.3 实测单步耗时（hidden-only 真实训练路径 + checkpoint + bf16 修复后）

| ctx | checkpoint | 单步 | 峰值 | 判断 |
|---|---|---|---|---|
| **4096** | on | **26.9 s**（iter2 稳态 15.1 s） | 12.56 GiB | ✅ **唯一可用** |
| 8192 | on | 1149.5 s | 25.98 GiB | ❌ 换页，慢 42× |
| 9216 | on | OOM | — | ❌ |
| 4096 / 6144 / 8192 | **off** | 全 OOM | — | ❌ checkpoint 不可关 |

**ctx 8192 慢 42× 的机制**：`reserved = 25.98 GiB` > 物理 11.91 GiB，Windows WDDM 把系统内存
当显存后备存储，权重/激活在 PCIe 上往返 → 不是 O(n²) 的 4×，而是 42×。

### 2.4 bf16 修复（本轮最大收益，5.8×）

`prepare_model_for_kbit_training` 会把**全部 179 个**非量化参数转 fp32（不只是 lm_head/embed，
还包括每层 conv1d.weight / A_log / dt_bias / 各种 norm）。这些参数每次 forward 都要 cast。

| 配置 | forward | 峰值 | alloc |
|---|---|---|---|
| prepare 后（fp32 参数） | **6.616 s** | 13.02 GiB | 10.92 GiB |
| 全转 bf16 | **1.144 s** | 8.20 GiB | 7.13 GiB |
| | **5.8×** | **省 3.79 GiB** | **省 3.79 GiB** |

修法见 [train_qlora9b.py](scripts/train_qlora9b.py) 第 182-203 行（无条件全量转换）。

---

## 3 数据准备

### 3.1 最终数据集清单（ctx 4096 切分版，已生成并校验）

| 用途 | 文件 | 行数 | token | 膨胀 |
|---|---|---|---|---|
| 2A RE 主体 | `kitty-reverse/train-kitty-core.jsonl` | 5602 | 1.32 M | ×1.000（不切） |
| 2A 轨迹 | `agent-traj/nemotron-swe/swe-8k-chunk4096.jsonl` | 1500 → **16651** | 12.32 → **47.19 M** | ×3.830 |
| 2A 轨迹 | `agent-traj/swe-rebench/rebench-8k-chunk4096.jsonl` | 150 → **478** | 1.23 → **1.46 M** | ×1.185 |
| 2A 轨迹 | `agent-traj/deepswe/deepswe-8k-chunk4096.jsonl` | 113 → **424** | 0.93 → **1.14 M** | ×1.227 |
| 2C 长上下文 | `agent-traj/nemotron-swe/swe-16k-chunk4096.jsonl` | 500 → **14280** | 8.20 → **39.90 M** | ×4.866 |
| 2B NSFW | `nsfw/train-{cont,multi,scene,style,expand}.jsonl` | 13668 | 15.45 M | ×1.000（不切） |
| （参考） | `nsfw/nsfw-glossary-merged.jsonl` | 283 | 0.06 M | 不训练 |

**轨迹合计**：2263 → **31833 行**，22.68 M → **89.69 M token**，膨胀 **×3.954**。

元信息：[train/lines/9b-oxcoder/data/agent-traj/CHUNK-MANIFEST.json](data/agent-traj/CHUNK-MANIFEST.json)

**校验全绿**：字符覆盖 1.000000、超 ctx 0、无损失败 0、label 全 -100 行 0、空 assistant 0。

**膨胀的代价**：约 79% 的训练 token 是重复的 system+user 模板（Nemotron system 固定 1694 +
user 固定 1274 = 底噪 2968 token，占 ctx 4096 的 72%）。这是 ctx 4096 的固有代价，已最小化。

**注意**：`kitty-reverse/re-qc/silver.jsonl`（8815 条）是 QC 中间产物，**不是训练集**。

### 3.2 无损切分脚本（已写好并全量验证）

```bash
# 位置
train/lines/_shared/scripts/chunk_train_samples.py

# 只审计不写盘（看膨胀率）
train/.venv/Scripts/python.exe train/lines/_shared/scripts/chunk_train_samples.py \
  --in-dir train/lines/9b-oxcoder/data/agent-traj --audit --ctx 4096

# 实际切分 swe-16k（只有它需要）
train/.venv/Scripts/python.exe train/lines/_shared/scripts/chunk_train_samples.py \
  --in train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-16k.jsonl \
  --out train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-16k-chunk4096.jsonl \
  --ctx 4096 --overlap 256
```

**切分规则**：
- 切点优先级 `\n[CALL `（工具步边界）> `\n\n` > `\n`
- 续段 user 前缀带上一段末尾 800 字符（`<carry_over>`），训练时不计 loss
- 校验：区间必须 `[0, len)` 无缝覆盖，允许 overlap，**零内容丢失**

**已验证**：三档 ctx × 三目录全量审计，字符覆盖恒等于 `1.000000`，超 ctx 行 0，无损校验失败 0。

---

## 4 环境清单

| 依赖 | 版本 | 状态 |
|---|---|---|
| Python | 3.13.9 | ✅ 用 `train/.venv/Scripts/python.exe`（**不是** anaconda base） |
| torch | 2.9.1+cu130 | ✅ |
| transformers | 5.20.2 | ✅ |
| trl | 1.16.0 | ✅ |
| peft | 0.21.2 | ✅ |
| bitsandbytes | 0.50.2 | ✅ |
| accelerate | 1.15.0 | ✅ |
| triton-windows | 3.8.0.post29 | ✅ liger 底座 |
| liger-kernel | 0.8.5 | ⚠️ 已装，但 `use_liger=True` 集成不支持 Qwen3_5（已用手写 Trainer 绕过） |
| **flash-linear-attention** | **0.6.0** | ✅ **已装且已生效**（实测闭包 `implementation=fla.ops.gated_delta_rule.chunk`，`is_new_implementation=True`） |
| causal-conv1d | — | ⚠️ pip 装不上（无 nvcc/MSVC），但 **FLA+Triton 替身已打通**（`train/lines/_shared/scripts/causal_conv1d.py`，零拷贝 8.9–10x、packing 可用），见 [`CAUSAL-CONV1D.md`](CAUSAL-CONV1D.md) |
| **flash-attn（SDPA flash）** | — | ❌ **torch 未编译 flash；cuDNN attention 拒绝 head_dim>128（Qwen3.5 是 256）** |

---

## 5 速度优化

### 5.1 已做（均有实测）

| 优化 | 效果 | 位置 |
|---|---|---|
| 手写 `LigerSFTTrainer`（分块 CE，chunk=1024） | CE 显存 **5102 → 509 MiB（省 90%）** | `train/lines/_shared/scripts/liger_ce.py` |
| `prepare_model_for_kbit_training` 后把 lm_head/embed 转回 bf16 | allocated **10.91 → 7.36 GiB** | `train_qlora9b.py` |
| `low_cpu_mem_usage=True` | RAM **27.5 → 10.3 GB** | 同上 |
| CPU 限 8 线程 + BelowNormal 优先级 | 消除 100% 尖峰卡顿 | 同上 |
| `low_cpu_mem_usage` + bf16 大表 | 加载后 RAM 10.3 GB（远低于 31.5 GB 上限） | 同上 |

### 5.2 待做（按收益排序）

| # | 优化 | 预期收益 | 难度 | 说明 |
|---|---|---|---|---|
| 1 | 确认 `attn_implementation=sdpa` 且实际走 mem_efficient | 避免误走 math 后端（慢 2–3×） | 低 | flash 不可用、cuDNN 拒绝 head_dim 256，mem_efficient 是唯一最优解 |
| 2 | 只对部分层开 gradient checkpointing | 省 20–30% 时间 | 中 | 全层 checkpoint 会多算一次 forward |
| 3 | ctx 4096 切分数据生成 | 已完成，见 CHUNK-MANIFEST.json | 已完成 | 膨胀 ×3.954，零丢失 |
| 4 | 确认 `paged_adamw_8bit` 已启用 | 省 0.3 GiB | 低 | — |

### 5.2.1 速度瓶颈实测分解（**两轮纠正，最终结论是 dtype cast**）

**第一轮纠正**：旧判断「24 层 linear_attn 走 PyTorch 参考实现」已被证伪 —— fla 0.6.0 早已装好并生效：

```
@use_kernel_func_from_hub_with_fallback("chunk_gated_delta_rule","fla")
  → _KERNELS_INTERNAL_PATH_MAPPINGS: "ops.gated_delta_rule"
  → 实测闭包: implementation = chunk_gated_delta_rule (fla.ops.gated_delta_rule.chunk)
              is_new_implementation = True
  → 24 层 linear_attn 已经走 triton kernel
```

**第二轮纠正（决定性）**：profile 显示 attention 根本排不进前 18：

| 算子 | 占比 | 调用次数 |
|---|---|---|
| `aten::add` | **20.62%** | 1078 |
| `aten::copy_` | **17.41%** | 1256 |
| `aten::_to_copy` | **14.24%** | 896（dtype 转换） |
| `aten::reshape` | 2.68% | 932 |
| SDPA / attention / cutlass | **未进 top 18** | 占比 < 5% |

三者合计 **52%**，全部是 **4bit 反量化 + dtype 转换**。根因：
`prepare_model_for_kbit_training` 把全部 **179 个**非量化参数转 fp32（不只 lm_head/embed，
还包括每层 conv1d.weight / A_log / dt_bias / 各种 norm）。全转回 bf16 后：

| 配置 | forward | 峰值 | alloc |
|---|---|---|---|
| fp32 参数 | **6.616 s** | 13.02 GiB | 10.92 GiB |
| 全转 bf16 | **1.144 s** | 8.20 GiB | 7.13 GiB |

**head_dim 256 的现状（确认不是瓶颈，且无解）**：

| Backend | 可用 | 原因 |
|---|---|---|
| FLASH | ❌ | `Torch was not compiled with flash attention`；PyPI 无 Windows 轮子（`pip download --only-binary=:all:` → No matching distribution） |
| cuDNN | ❌ | `head_dim should be no more than 128`（Qwen3.5 是 256） |
| EFFICIENT | ✅ | 唯一可用的优化后端 |
| MATH | ✅ | 兜底，慢 2–3× |

即使打通也只影响那 8 层的 < 5%，**不值得投入**。

### 5.3 不可做（已验证失败，别再试）

| 方案 | 失败原因 |
|---|---|
| `SFTConfig(use_liger=True)` | transformers 的 liger 集成只覆盖 39 个模型，Qwen 系只有 `qwen2vl_mrope`，**不含 Qwen3_5** |
| `packing=True` | 需要 `causal_conv1d`，装不上；且跨样本拼包会让 linear_attn 状态串联 |
| `causal-conv1d` 直接 pip 装 | 无 nvcc/MSVC；build isolation 会拉 torch 2.14.1 覆盖 2.9.1 |
| `LFLCE.apply(...)` 直接调用 | 返回 tuple、参数个数对不上（22 vs 19）、不支持 kwargs → 已改手写分块 CE |
| `flash-attn` 包 | Windows 无预编译轮子；需 MSVC；head_dim 256 支持有限 |
| **再装/再找 fla** | **已装且已生效，别再折腾** |
| `torch.compile` | Windows 上 9B QLoRA 编译不稳定，收益不确定，暂不做 |

---

## 6 坑清单

### 6.1 已踩过（别再踩）

| # | 坑 | 症状 | 解法 |
|---|---|---|---|
| 1 | `prepare_model_for_kbit_training` 把 lm_head/embed 转 fp32 | 9 次 CUDA OOM `Tried to allocate 4.00 GiB` | 加载后转回 bf16（各 3.79 → 1.9 GiB） |
| 2 | `from_pretrained` 缺 `low_cpu_mem_usage=True` | RAM 27.5/31.5 GB（87%），系统卡死 | 加上即可，RAM 降到 10.3 GB |
| 3 | `use_liger=True` 不支持 Qwen3_5 | 静默走回退，logits 4 GiB 照样占 | 手写 `LigerSFTTrainer` |
| 4 | `LFLCE.apply` 签名不兼容 | `forward() takes 4 to 19 positional arguments but 22 were given` | 自己写分块 CE，不调 liger op |
| 5 | `causal-conv1d` build isolation | 暗地里装 torch 2.14.1，破坏环境 | `--no-deps` 装 liger；causal-conv1d 放弃 |
| 6 | CPU 100% 尖峰导致系统卡顿 | 间歇性卡 | `set_num_threads(8)` + `set_num_interop_threads(1)` + psutil BelowNormal |
| 7 | Python PATH 是 0 字节商店别名 | 执行无输出 ≠ 没装 | 必须全路径 `train\.venv\Scripts\python.exe` |
| 8 | 控制台 GBK 乱码 | `����` | `PYTHONIOENCODING=utf-8` |
| 9 | jsonl 里的 `\u2028` | `splitlines()` 把一行切成两行 → JSON 解析失败 | 用 `.split("\n")` |
| 10 | HF 镜像 429 + Windows symlink | `FileNotFoundError: ..\blobs\<hash>` | `HF_HUB_DISABLE_SYMLINKS=1` |
| 11 | 仓库里有 `nul` 文件 | `git add` 报 `short read while indexing nul` | `.gitignore` 加 `nul` |
| 12 | 百度网盘同步目录间歇不可见 | `Test-Path` False 但 `-Recurse` 能列出 | 重试 / 换 API |

### 6.2 预判（开工前必须处理）

| # | 坑 | 风险 | 处理 |
|---|---|---|---|
| **A** | **chat_template 无 `{% generation %}` 标记** | `SFTConfig(assistant_only_loss=True)` 失效或报错，导致 **user 也被算 loss** | ✅ **已解决**：`train/lines/_shared/scripts/label_builder.py`，自检全绿（kitty p50 可训练占比 0.549 / swe-8k 0.638 / nsfw 0.854，零全 -100 行） |
| **A2** | Qwen3.5 模板在 `add_generation_prompt=True` 时**多插 `</think>\n`**，完整渲染时不插 | 直接用 `len(prompt_text)` 定位边界会偏移 8 字符，导致 `assistant` 字样漏进 labels | ✅ **已解决**：用两者最长公共前缀作边界 |
| **B** | 续段 `<carry_over>` 可能让模型学成"复述上文" | 质量下降 | 训练时 carry 段 label 全 `-100`；只对 assistant 正文算 loss；抽检 5 条看梯度 |
| **C** | 引擎未停，显存被占 | 启动即 OOM | 开训前 `nvidia-smi` 确认 < 2000 MiB |
| **D** | `meta` 字段被 SFTTrainer 丢弃 | 无法回溯数据来源 | 训练前把 `meta.__src` 折进 `id` 字段 |
| **E** | ctx 4096 时 `per_device_train_batch_size=2` | 实测峰值 12.56 GiB 已贴上限，bs=2 必 OOM | **bs 固定 1**，用 `gradient_accumulation_steps=16` 放大 |
| **F** | bitsandbytes 8bit optimizer 在 Windows 偶发不稳 | 训练中途崩 | 备选 `adamw_torch`（多 0.5 GiB） |

---

## 7 开工前置动作（逐条可执行，均为非训练操作）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI

# ① 停引擎，确认显存干净（期望 < 2000 MiB）
nvidia-smi --query-gpu=memory.used --format=csv,noheader

# ② ctx 4096 切分数据 -- 已生成，无需重跑（见 CHUNK-MANIFEST.json）
#    如需重建：
#    train\.venv\Scripts\python.exe train\lines\_shared\scripts\chunk_train_samples.py `
#      --in train\lines\9b-oxcoder\data\agent-traj\nemotron-swe\swe-8k.jsonl `
#      --out train\lines\9b-oxcoder\data\agent-traj\nemotron-swe\swe-8k-chunk4096.jsonl `
#      --ctx 4096 --overlap 256

# ③ 校验切分产物（期望：覆盖 1.000000 / 超ctx 0 / 无损失败 0）
train\.venv\Scripts\python.exe train\lines\_shared\scripts\label_builder.py --scan `
  train\lines\9b-oxcoder\data\agent-traj\nemotron-swe\swe-8k-chunk4096.jsonl --ctx 4096

# ④ 验证 fla 已生效（0.6.0 已装，**不需要再装**）
train\.venv\Scripts\python.exe -c "from fla.ops.gated_delta_rule import chunk_gated_delta_rule; print('fla ok')"

# ⑤ labels 构造器自检（坑 A 的解法）
train\.venv\Scripts\python.exe train\lines\_shared\scripts\label_builder.py --selftest

# ⑥ 确认 bf16 全量转换生效（加载后应立即打印 "179 个 fp32 参数转回 bf16"）
#    train_qlora9b.py 已内置，跑 --dry-run 或看日志首屏
```

---

## 8 冒烟验证（**2026-10-28 已实跑通过，并修掉 2 个致命 bug**）

### 8.1 实测结果（20 条 kitty / ctx 4096 / 1 步 / liger CE）

```
[load] arch=Qwen3_5ForConditionalGeneration loader=AutoModelForImageTextToText
[vram] 402 个 fp32 参数转回 bf16，allocated = 7.35 GiB
[lora] targets = down/gate/up/out_proj, in_proj_{a,b,qkv,z}, q/k/v/o_proj （12 类）
trainable params: 86,556,672 || all params: 9,496,370,416 || trainable%: 0.9115
1/1 [00:02, 2.71s/it]  train_loss 4.562   （首次含暖机 13.48 s，loss 4.656）
[OK] adapter → train/lines/9b-oxcoder/out/_smoke2/final
```

| 项 | 期望 | 实测 | 结果 |
|---|---|---|---|
| 加载后显存 | ≤ 7.5 GiB | **7.35 GiB** | ✅ |
| 单步耗时（20 条短样本） | 15–27 s | **2.7 s**（稳态） | ✅ 更快（样本短） |
| 是否 OOM | 否 | 否 | ✅ |
| loss | 4–5（未训练基座） | **4.562** | ✅ |
| 数据通过率 | 无丢弃 | 20/20，`Dropping fully masked` = 0 | ✅ |

### 8.2 冒烟发现并修复的 2 个致命 bug

| # | bug | 后果 | 修法 |
|---|---|---|---|
| **A1** | 原脚本把 messages 渲染成**单列 text**，SFTTrainer 对**全部 token 算 loss** | 模型会学着生成 system 提示和用户提问，训练报废 | 改 prompt/completion 双列 + `completion_only_loss=True`；trl 内部执行 `labels[completion_mask==0] = -100` |
| **A2** | `add_generation_prompt=True` 补 `<think>\n`，但 completion 直接接正文 | **缺 `</think>` 闭合**，格式非法，模型学到"永不结束思考" | completion 前补空思考块 `</think>\n\n`（数据自带 `<think>` 时原样保留） |

**A2 实测证据**：`add_generation_prompt=True 比 False 多出: '<|im_start|>assistant\n<think>\n'`

**修复后格式（已验证）**：

```
<|im_start|>assistant\n<think>\n</think>\n\nkitty_sym — action 取 exports / imports / resolve。...
  ├ <think> 存在
  ├ </think> 存在
  └ 顺序正确（think → /think → 正文）
prompt 84 tok / completion 99 tok
```

### 8.3 ★ 致命坑：`gradient_accumulation_steps=16` 会卡死（2026-10-28 实测定案）

**现象**：`ga=16` 时训练在**第 1 步之后无限挂起**——GPU 100%、显存 11.9 GiB 不释放、
tqdm 停在 `1/N`、JSONL 无新记录。连续 3 次复现，paged_adamw_8bit 与 adamw_torch 都一样。

| 配置 | 结果 | 单步 | 每样本 | loss |
|---|---|---|---|---|
| **ga=16** + paged_adamw_8bit | ❌ 卡在 1/12 | 139 s | — | 无 |
| **ga=16** + adamw_torch | ❌ 卡在 1/4 | 76 s | — | 无 |
| **ga=4** + adamw_torch | ✅ 8 步完成 | 2.37 s | 0.66 s | 3.469 |
| **ga=1** + adamw_torch | ✅ 20 步完成 | 0.72 s | 0.72 s | 3.267 |

→ **ga 上限 4，16 必挂。optimizer 不是原因。**

**速度归一化**：ga=1 与 ga=4 的每样本时间一致（0.66–0.72 s），
说明 **ga 只改变分组方式，不改变总时长**；总时长 = 总样本数 × 单样本时间。

**单样本时间随长度变化（实测三点）**：

| 样本长度 | 时间 |
|---|---|
| 270 token（kitty 均值） | **0.72 s** |
| 1590 token（2A 均值） | **≈4.3 s**（2.7 ms/token 推算） |
| 4096 token（满 ctx） | **47 s** |

**loss 曲线验证（ga=1 / 20 步 / kitty 样本）**：

```
step  5: loss 3.9406  grad_norm 3.80  lr 4e-05    epoch 0.25
step 10: loss 3.5281  grad_norm 5.94  lr 9e-05    epoch 0.50
step 15: loss 2.5953  grad_norm 3.75  lr 6.5e-05  epoch 0.75
step 20: loss 3.0031  grad_norm 8.06  lr 2.4e-06  epoch 1.00
        平均 3.2668
```

loss 从 3.94 降到 2.60（step 15），**下降 34%**，学习正常。

**用 ga=4 + adamw_torch 重估时长**：

| 阶段 | 样本数 | 单样本 | 时长 |
|---|---|---|---|
| 2A | 34359 | ~4.3 s | **41 h** |
| 2B | 13668 | ~3.2 s | **12 h** |
| 2C | 14280 | ~7.5 s | **30 h** |
| 合计 | 62307 | | **约 83 h（3.5 天）** |

**附带修好的基础设施坑**：tqdm 的 stderr 重定向到文件会被块缓冲，长跑时日志几十/上百分钟不更新。
已加 `_JsonlLog` 回调（`on_log` → `train-log.jsonl`，每 `logging_steps` 追加一行并 flush）：
`tail -f train/lines/9b-oxcoder/out/<阶段>/train-log.jsonl` 即可实时看曲线。

**开训命令必须用 `--ga 4 --optim adamw_torch`。**

### 8.4 ★ 显存碎片 + WDDM 换页（2026-10-28 完整排查，也是"系统间歇性卡顿"的根因）

**症状**：训练第 47 步前 2.49 s/步正常，第 48 步起单调恶化 23.75 → 53.84 → 57.93 → 68.91 → 93.86 s/步，
同时**整个 Windows 系统间歇性卡顿**。nvidia-smi 显示 util=100% 但 `power.draw=53W`、`P2`、`throttle=0x400(GPU Idle)`。

**60 步逐帧显存轨迹（mem-trace.jsonl，每步记录）**：

```
step  1: alloc 7.848  reserved  8.658  peak 13.043  free 1.862
step  2: alloc 7.848  reserved  9.109  peak 13.043  free 1.417
step 10: alloc 7.848  reserved  9.621  peak 13.043  free 0.926
step 53: alloc 7.848  reserved 10.230  peak 13.043  free 0.331
step 59: alloc 7.848  reserved 10.922  peak 13.043  free 0.000  ← 物理显存归零
```

**三条硬结论**：

| 结论 | 判据 |
|---|---|
| **不是显存泄漏** | `alloc_gib` 60 步恒定 7.848，一步没涨 |
| **是碎片累积** | `reserved` 单调爬升 8.658 → 10.922，`free` 从 1.862 降到 0 |
| **`peak=13.043` 是假数字** | 从第 1 步就恒定不变，且与 `free=1.3` 矛盾 → 实际是 `from_pretrained` 加载 18.8 GB 权重的瞬时峰值，不是训练峰值 |

**"系统间歇性卡顿"的物理机制**：`reserved` 触顶后，Windows WDDM（无 `expandable_segments` 支持）
把系统内存当显存后备存储，权重/激活经 PCIe 往返 → GPU util 100% 但功耗只有 53W（假忙）→
**训练慢 30 倍，同时内存带宽被占，整个系统卡顿**。

**4 项修复（已验证，100 步全程稳定）**：

| # | 修复 | 位置 | 效果 |
|---|---|---|---|
| 1 | **卸载视觉塔** `model.model.visual = None` | train_qlora9b.py | 230 M 参数，alloc 7.848 → **7.621 GiB** |
| 2 | **硬限制显存** `torch.cuda.set_per_process_memory_fraction(0.93)` | 同上 | 越过物理边界时明确 OOM，**不再让 WDDM 换页拖垮系统** |
| 3 | **Liger CE 分块** 1024 → 256（`LIGER_CE_CHUNK` 可配） | liger_ce.py | 峰值降约 0.25 GiB |
| 4 | **按长度分桶重排数据**（64 token 一档，桶内打乱） | bucket_by_length.py | 消除变长分配，**碎片停止累积** |
| 5 | 训练前 `reset_peak_memory_stats()` | train_qlora9b.py | peak 不再被加载峰值污染 |

**修复后验证（fix1 跑 100 步）**：

```
step  1: reserved 9.129  free 1.408
step 46: reserved 9.236  free 1.299
step 95: reserved 9.236  free 1.301   ← 55 步纹丝不动
step100: reserved 9.236  free 1.295
速度 2.36–2.56 s/步（全程无掉速）   loss 2.94 → 2.28（下降中）
```

**分桶数据生成**：

```bash
train/.venv/Scripts/python.exe train/lines/_shared/scripts/bucket_by_length.py \
  --in train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl \
  --out train/lines/9b-oxcoder/data/kitty-reverse/kitty-core-bucketed.jsonl --bucket 64
```

**开训环境变量（两个都要）**：

```bash
PYTORCH_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.80   # 注意：不是 PYTORCH_CUDA_ALLOC_CONF（已弃用）
VRAM_FRAC=0.93                                                              # 显存硬上限比例
```

### 8.5 开训前仍需人工确认

| # | 项 | 判据 |
|---|---|---|
| 1 | 引擎已停 | `nvidia-smi` < 2000 MiB |
| 2 | 加载后 RAM | ≤ 12 GB |
| 3 | 长样本单步 | 用 1 条满 ctx 4096 轨迹跑 1 步，确认 15–27 s 且不 OOM |
| 4 | 混比数据集已生成 | 见 §9 |

---

## 9 训练参数基线（三段式，开训时直接用）

```text
公共：
  quantization      = 4bit NF4 + double_quant + bf16 compute
  lora_r            = 32        lora_alpha = 64      lora_dropout = 0.05
  target_modules    = q/k/v/o + gate/up/down + linear_attn 投影
  per_device_bs     = 1         grad_accum = 16
  lr                = 1e-4      scheduler = cosine    warmup = 3%
  gradient_checkpointing = True (non-reentrant)
  packing           = False     use_liger = False（走手写 Trainer）
  low_cpu_mem_usage = True      大表 bf16

2A  RE + 轨迹     ctx 4096   1 epoch   mix-2a.jsonl  34359 行 / 54.63 M / 833 步（kitty×3 + 轨迹全量）
2B  NSFW 生成      ctx 4096   1 epoch   mix-2b.jsonl  13668 行 / 16.10 M / 245 步
2C  长上下文       ctx 4096   1 epoch   mix-2c.jsonl  14280 行 / 39.90 M / 608 步
```

**速度预估（实测基线）**：

| 阶段 | 步数 | 单步 | 时长 |
|---|---|---|---|
| 2A（kitty + 轨迹 17553 段，accum 16） | ≈ 1480 | 15–27 s | **6–11 h** |
| 2B（nsfw 13668，ctx 4096） | ≈ 850 | 15–27 s | **3.5–6.4 h** |
| 2C（swe-16k 14280 段） | ≈ 890 | 15–27 s | **3.7–6.7 h** |
| **合计** | ≈ 3220 | | **约 13–24 h** |

推导依据：轨迹切分后 89.69 M token ÷ (4096 × 16) = 1368 步。
`26.9 s` 是实测均值（含首次编译），`15.1 s` 是 iter2 稳态，按区间给。

---

## 10 回滚点

| 产物 | 回滚方式 |
|---|---|
| LoRA 权重 | 每个 stage 结束存一次 `checkpoint-*`，保留最近 2 个 |
| 切分数据 | 原始 jsonl 未改动，重跑脚本即可 |
| 环境 | `train/.venv` 独立，破坏后重建；`causal-conv1d`/`fla` 装坏可 `pip uninstall` |
| 计划 | 本文件与 `PLAN-OXCODER-POSTTRAIN.md` 都在 git 里（`train/data/` 除外） |

---

## 11 一页速查（给接手的 agent）

```text
1. 在哪一步        → P2 前置已完成（ctx 决策 + 数据切分 + labels 构造器），可开训
2. ctx 用多少      → **4096（硬件硬上限，实测 26.9s/步；8192 需 1149s，9216 OOM）**
3. 数据怎么来      → 四份已生成：*-chunk4096.jsonl（轨迹）+ kitty + nsfw；见 CHUNK-MANIFEST.json
4. 最大的坑        → chat_template 无 generation 标记，必须用 label_builder.py 手工构造 labels
5. 最大的瓶颈      → prepare_model_for_kbit_training 把 179 个参数转 fp32（已修为全量 bf16，5.8×）
6. 显存够不够      → ctx 4096 峰值 12.56 GiB / 上限 11.91 GiB（checkpoint 必须开，关了必 OOM）
7. 开训前必做      → 停引擎 + 确认 bf16 全量转换 + label_builder 自检 + 冒烟 7 项
```
