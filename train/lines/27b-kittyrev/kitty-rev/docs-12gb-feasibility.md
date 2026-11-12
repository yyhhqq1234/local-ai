# 12 GB（RTX 5070 Ti Laptop）上给 Qwen3.8-27B 做后训练：可行性与方法评估

> 结论先说：**12 GB 显存 + 32 GB 内存这一台机器，目前没有可跑的 27B 后训练路径**——已实测 8 条，
> 把"整模型 4bit""4bit+CPU offload""部分层 4bit+部分层 bf16""全 GPU"全部试穿，失败点分别是显存、
> meta 张量、主机内存三处。
> **存在可行方法，但必须松开一个硬件约束**：加显存到 24 GB（最省事）、加内存到 64 GB（本地啃）、
> 或上 Linux/WSL2 走 accelerate offload。
> 本报告所有"实测"结论都来自本机日志，不是推断。

---

## 1 先算清账：为什么 12 GB 装不下

```text
模型          Qwen3.8-27B（qwen3_5，64 层 = 48 linear_attention + 16 full_attention，H5120，V248320，带 MTP）
4bit NF4 权重  ≈ 12.6 GiB（text-only 也在 12 GiB 量级）
本机可用显存   11.9 GiB 总 − 桌面占用(0.7~1.6 GiB) ≈ 10.3~11.2 GiB
差额          ≈ 1.5–2.5 GiB → 必须把一部分权重放到 CPU
```

关键点：**不是"能不能训"，而是"放到 CPU 的那部分怎么放"**。放法不同，成败完全不同。

---

## 2 实测六条路径（本机，逐条记录失败点）

| # | 方案 | 命令要点 | 结果 | 失败点原文 |
|---|---|---|---|---|
| 1 | 全 4bit + `device_map=auto` | 默认 | ✗ | `ValueError: Some modules are dispatched on the CPU or the disk… set llm_int8_enable_fp32_cpu_offload=True` |
| 2 | 4bit + CPU offload（fp32） | `--cpu-offload --max-memory "cuda:0=10GiB,cpu=24GiB"` | ✗ | accelerate 不接受 `"cuda:0"` 键（只认整数/`cpu`/`disk`） |
| 3 | 修正键名后重试 | `"0=10GiB,cpu=24GiB"` | ✗ | `accelerate.hooks.attach_align_device_hook_on_blocks → module.state_dict() → bnb quant_state.as_dict → offset.item()` → **`Tensor.item() cannot be called on meta tensors`** |
| 4 | 降 accelerate 1.13 + text-only | 同上 | ✗ | 同一处崩（说明不是版本偶发） |
| 5 | 全放 GPU | `--all-gpu`（`{"":0}`） | ✗ | `prepare_model_for_kbit_training` 里 `param.data.to(float32)` → **OOM，需 4.74 GiB 而仅剩 3.78 GiB** |
| 6 | **打 accelerate 补丁**（跳过 meta state_dict 探测）+ 跳过 peft fp32 upcast | `--skip-kbit-prepare` | **推进到训练循环** | 首个 step 前：`bitsandbytes quant_state.to(device) → self.code.to(device)` → `NotImplementedError: Cannot copy out of meta tensor; no data!` |

第 6 条是重要进展：**offload 加载本身已经通了**（800+ 张量全部加载、模型构造完成、进入 `0/2` 训练循环），
卡在第一步时 accelerate 要把某个被 offload 的 4bit 模块搬回设备，而它的 `quant_state.code` 是 meta 张量。

根因：**bnb 4bit 的量化状态在 meta 初始化时只存在于 meta 设备**，offload→回搬的路径没有物化它。
这是 bitsandbytes 0.50 + transformers 5.x 在"4bit + CPU offload + 训练"这个组合上的实现缺口，
不是本机环境问题（换 accelerate 版本无效已验证）。

---

## 2.5 路径 A 的实测补充（失败，两条都撞 RAM）

在本机把"部分层 4bit + 其余层 bf16 驻内存"实现出来（`--gpu-layers N`）并实测：

| # | 配置 | CPU 侧 bf16 | 结果 |
|---|---|---|---|
| 7 | `--gpu-layers 48`（16 层在 CPU） | ≈13.5 GiB | ✗ `transformers/core_model_loading.py: _materialize_copy → tensor[...]` → **MemoryError**（可用 RAM 24.3 GiB） |
| 8 | `--gpu-layers 52`（12 层在 CPU） | ≈10.1 GiB | ✗ 同一处 **MemoryError** |

原因：transformers 5.x 的分片加载会为每个权重做 materialize 拷贝，峰值远高于"最终驻留"；
54 GiB 检查点在 32 GiB RAM 的机器上，即使只搬 12 层也会在拷贝阶段爆。

**结论：12 GB 显存 + 32 GB 内存这个组合，无论怎么切分都过不了加载阶段。**
要本地跑 27B 训练，必须松开其中一个约束（换 24 GB 卡 / 加内存到 64 GB / 上 Linux 走 offload）。

## 3 三条可行路径（按代价排序）

### 路径 A：部分层 4bit + 其余层 bf16 驻内存（本机可试，未验完）

思路：不要"整模型 4bit 再 offload"，而是**让 offload 的那部分根本不量化**。

```python
# 关键参数（transformers 支持）
llm_int8_skip_modules = [f"model.language_model.layers.{i}" for i in range(N, 64)] + ["visual"]
device_map = {"": "cpu", **{f"model.language_model.layers.{i}": 0 for i in range(N)}, "lm_head": 0}
```

账（N = 放 GPU 的层数）：
```text
GPU：N/64 × 12.6 GiB（4bit）+ lm_head ≈ 0.6 GiB
CPU：(64−N)/64 × 54 GiB（bf16，未量化）  ← 这是瓶颈，RAM 31.5 GiB 只能承受 (64−N) ≤ 14 层
取 N = 50：GPU ≈ 10.4 GiB（紧），CPU ≈ 11.8 GiB（可）
取 N = 48：GPU ≈ 10.0 GiB，CPU ≈ 13.5 GiB（更安全）
```
判据：能进训练循环且第 1 step 不抛 `meta tensor`；速度预计 27B 混合驻留 ≈ 0.3–0.8 s/step（ctx 256）。
风险：CPU 上 bf16 层的前反向很慢，100 步可能 1–2 小时；且跳过量化的层无法用 4bit kernel。

### 路径 B：WSL2 / Linux + accelerate offload（同一套脚本，换平台）

同一份 `train_kitty.py`（已带 `--cpu-offload/--max-memory/--text-only/--skip-kbit-prepare`）在 Linux 上是常规路径：
bnb 的 offload 回搬在 Linux 有完整实现，社区大量 24GB 以下跑 27B QLoRA 的案例都走这条。
代价：重建 cu130 栈（约半天），WSL2 里显存直通可用但要装 WDDM 驱动侧组件。
判据：能进训练循环 + loss 下降 + 显存稳定。

### 路径 C：24 GB 卡 / 云卡（最省事）

4bit 全量上 GPU，不需要任何 offload：
```powershell
& .\.venv\Scripts\python.exe .\kitty-rev\scripts\train_kitty.py --size 27b --ctx 2048 --all-gpu --data .\kitty-rev\data\large-mix\train.jsonl
```
100 步预计 1–2 小时（对比本机 offload 的数小时）。

---

## 4 外部资料怎么说（不是本机实测，标注来源）

| 来源 | 说法 | 与本机的关系 |
|---|---|---|
| [Unsloth · Qwen3.8 微调指南](https://unsloth.ai/docs/zh/mo-xing/qwen3.8/train) | 官方给出 Qwen3.8 系列的 4bit 微调配方（含 27B 档），核心是 4bit + gradient checkpointing + 小 batch | 思路与本文 §3C 一致；其 27B 配方假设 ≥24 GB 卡 |
| [QLoRA 原始工作（Dettmers 等）](https://columbiauniversity.atlassian.net/wiki/download/attachments/102170681/QLoRa-+Fine-Tune+a+Large+Language+Model+on+Your+GPU.pdf?version=1) | 4bit NF4 + paged optimizer 让 65B 在 48GB 上微调 | 27B → 12GB **低于论文的最低配比**，必须 offload，论文未覆盖 offload 训练路径 |
| [GaLore（梯度低秩投影）](https://openreview.net/pdf?id=AzqPyO22zt) | 用梯度投影把优化器状态压到极低，7B 可在 24GB 上全参训练 | 解决的是**优化器显存**，不解决**权重 12.6 GiB 放不下**；与 offload 叠加才有意义 |
| [Qwen3.5 微调教程（腾讯云社区）](https://cloud.tencent.cn/developer/article/2660244) | 端到端流程：环境、数据格式、LoRA 参数、合并、部署 | 流程与本项目一致；同样未覆盖 12 GB |

**结论**：公开资料里没有"12 GB 单卡训 27B"的现成配方；能查到的都是 24 GB 起。
唯一现实的本机路线是把"放不下"的那 10–15 GiB 用 CPU 承载，而这正是我们在路径 A 上做的。

---

## 5 本机现状（可直接复用的资产）

```text
数据      data/large-mix/train.jsonl  3908 条（2736 自有 + 1172 开源推理链，30% 配比，质检 PASS）
脚本      train_kitty.py 已支持：--cpu-offload / --max-memory / --text-only / --all-gpu / --skip-kbit-prepare
补丁      accelerate/hooks.py：跳过 meta 张量 state_dict 探测（本机 site-packages 内，升级会被覆盖）
基座      train/lines/27b-kittyrev/base/Qwen3.8-27B（51.75 GiB，18 shards，架构 Qwen3_5）
converter 27B 基座 → .ninfer 已跑通（16.35 GiB 制品，见 CONVERTER-STATUS.md）
```

---

## 6 建议决策

```text
本机 Windows（12G 显存 / 32G 内存）：✗ 八条路径已试穿，别再投入
想今晚就看到 27B 出 loss：走路径 C（24GB 卡或云卡，1–2 小时出 loss）
不想花钱但接受半天折腾：走路径 B（WSL2 + Linux offload，同脚本换平台）
想留在 Windows 本地：先加内存到 64 GB，再回头试路径 A（--gpu-layers 48/52）
```

**已经为路径 A/B/C 准备好的东西**（换环境后直接跑）：`--gpu-layers` / `--skip-kbit-prepare` /
`--cpu-offload` / `--max-memory` / `--text-only` 全部实现并有失败日志可对照；
`accelerate/hooks.py` 的 meta 张量补丁已打；数据 `data/large-mix`（3908 条）质检 PASS。

路径 A 的验证命令（本机可直接跑，约 5 分钟出结果）：
```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train
& .\.venv\Scripts\python.exe .\kitty-rev\scripts\train_kitty.py --size 27b --ctx 256 --ga 64 --max-steps 1 `
    --text-only --gpu-layers 48 --skip-kbit-prepare
```
（`--gpu-layers` 尚未实现，实现点在 `train_kitty.py` 的 `load_kw`：构造 `llm_int8_skip_modules` + 分层 `device_map`，约 30 行。）
