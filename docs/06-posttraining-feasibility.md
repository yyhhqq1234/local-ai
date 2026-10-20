# 06 · 后训练可行性指南（可行性判定 + 执行红线）

> 依据：`_research/微调能力-备案-20261020/`（备案号 `SHIYI-LOCALAI-MT-20261020`，4 轮分析已收口）
> 关系：**本文回答"能不能训、怎么训"**；`docs/03-posttraining.md` 回答"训练什么"（数据与验收）。
> 状态：结论已定稿；执行前置（Python/训练栈/converter）尚未满足。

---

## 1 一句话结论

```text
现部署的 .ninfer 不能就地微调（它是推理产物，99.5% 体量是量化块，引擎只有前向）。
可行链路：取同架构 bf16 基座 Qwen/Qwen3.8-27B → QLoRA → 合并 → GGUF → ninfer-v3 converter → 覆盖部署。
本机硬件：8B 级舒适、14B 贴边、27B 必须 offload。当前卡口不在算力，在【训练环境未装 + 无全精度基座 + converter 丢失】三项。
```

---

## 2 决策树（先看要做什么）

```text
想做什么？
├─ 给现部署的 27B 加强能力 ────────────→ 走 §4 全链路（含 converter 回炉），成本最高
├─ 验证"能不能训 / 数据格式对不对" ────→ 8B 基座 QLoRA + adapter 直接推理对比（§4 阶段 8，30 分钟）
├─ 只做 abliteration（去审查强化）─────→ 仅 8B；27B 需 bf16 + >12G 显存，本机不成立
├─ 27B 全参微调 ────────────────────────→ ✗ 不成立（54GB 权重 + 8×A100 级）
└─ 原地微调 .ninfer ────────────────────→ ✗ 不成立（无训练图/优化器）
```

---

## 3 硬件与显存数学（判据）

| 模型 | 方案 | 权重常驻 | 峰值 | 判定 |
|---|---|---|---|---|
| **27B** | QLoRA 4bit NF4 | ≈13.5 GB | 权重已超 12 GB 卡 | **必 offload** |
| 27B | LoRA bf16 | ≈54 GB | — | ✗ |
| **14B** | QLoRA 4bit | ≈7 GB | 11–12 GB | △ 贴边 |
| **8B** | QLoRA 4bit | ≈4 GB | 8–10 GB | **✓ 舒适** |

本机实测：RTX 5070 Ti Laptop **11.9 GB**（注册表 `qwMemorySize`；WMI 报 4GB 是 32 位截断，弃用）、RAM 31.5 GB、算力 **sm_120a**。

---

## 4 唯一可行链路（五段，每段有判据）

```text
① 环境       Python3.12 + torch cu130 + bnb0.50.2 + transformers≥5.8
             判据：torch.cuda.get_device_capability(0)==(12,0) 且显存 11.9
② 基座       HF_ENDPOINT=hf-mirror.com 拉 Qwen/Qwen3.8-27B（≈54 GiB，断点可续）
             判据：AutoConfig.architectures == ['Qwen3_5ForConditionalGeneration']
③ 训练       QLoRA：只挂 7 个 Linear；ctx 2048（27B 降到 512–1024）
             判据：前 20 step loss 单调下降、无 OOM、无 NaN
④ 合并        CPU 上 merge_and_unload → merged/（+54 GB，串行峰值）
             判据：merged 可 AutoModel 加载
⑤ 回炉       merged → GGUF f16 → ninfer-v3 converter → .ninfer → 覆盖部署
             判据：新 .ninfer 起引擎 /v1/models 200 + 实际推理 finish=stop
```

详细命令见备案包 `04-RUNBOOK.md`（已含现成脚本：`train/scripts/setup_env.ps1` / `fetch_base.py` / `train_qlora.py` / `merge.py`）。

---

## 5 版本锁定（唯一可行组合，别换）

```text
Python            3.12
torch             2.11.0+cu130 (win_amd64)   --index-url https://download.pytorch.org/whl/cu130
bitsandbytes      0.50.2 (win_amd64)
flash_attn        2.8.4 (cp312 / torch2.11 / cu130 / sm120 预编译)   ← 可选
transformers      >=5.8   （必须能识别 Qwen3_5ForConditionalGeneration）
peft / trl / accelerate / datasets   最新稳定
```

**禁项（本机无 MSVC，任何现场编译都会失败）**
```text
✗ 自编 flash-attn / deepspeed / bitsandbytes
✗ pypi 默认 wheel（CPU 版，报 "no kernel image is available"）
```

**退路（不装 FA）**：`torch 2.9.1+cu128` + `bnb 0.50.2`，注意力用 SDPA，功能不缺。

---

## 6 模型身份：一个必须记住的坑

| 项 | 值 |
|---|---|
| 产品名 | **Qwen3.8-27B** |
| HF `architectures` | `Qwen3_5ForConditionalGeneration` |
| `model_type` | `qwen3_5` / `qwen3_5_text` |
| 正确理解 | **`Qwen3_5*` 是 transformers 实现类名，不是版本号**（同类：Qwen2.5 至今写 `Qwen2ForCausalLM`） |

配套架构事实（影响训练参数）：64 层 = 48 linear_attention + 16 full_attention（4 层一循环）、H5120、V248320、MTP 头。

---

## 7 LoRA 挂载红线（该架构特有，挂错直接 NaN）

```python
# 只挂这 7 个 Linear
target_modules = ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]

# 禁止挂载（SSM/状态空间参数，破坏数值稳定性）
#   gdn/a_log, gdn/dt_bias, gdn/convolution, gdn/a_projection, gdn/b_projection, gdn/norm
#   vision.*（冻结）
```

---

## 8 执行前检查清单（当前多项未满足）

| # | 前置 | 现状 | 判据 |
|---|---|---|---|
| 1 | 系统 Python 3.12 | ✗ 未装（PATH 里是 WindowsApps 0 字节别名） | `python -V` = 3.12.x |
| 2 | torch cu130 | ✗ | `(12,0)` + 11.9 GB |
| 3 | transformers ≥5.8 | ✗ | `AutoConfig` 识别 `Qwen3_5*` |
| 4 | 全精度基座 | ✗ 本地只有 `.ninfer` | 54 GiB safetensors 可加载 |
| 5 | ninfer-v3 converter | ✗ 本机已丢失（原 `D:\Ab1-Swift\engine\tools` 已删） | 能从 GGUF 产出可加载 `.ninfer` |
| 6 | D 盘空间 | 164.5 GB 空闲 | 27B 串行峰值 108 GB（base+merged）；8B 峰值 32 GB |
| 7 | 训练期间停同步 | — | 百度网盘同步会打断 54 GB 训练资产 |
| 8 | 训练期间停引擎 | — | 引擎占显存 |

---

## 9 不可用路径（记录，别再试）

| 路径 | 状态 | 原因 | 替代 |
|---|---|---|---|
| 原地微调 `.ninfer` | ✗ | 引擎 `infer-serve.exe` 只有前向；容器是量化+索引 | 从 HF 基座训 |
| 从 `.ninfer` 反解 bf16 | △ 不划算 | 689 个量化张量占 12.75 GiB（99.5%），全模型近似 | 拉上游基座 |
| `D:\Ab1-Swift` 原始转换工作区 | ✗ | 目录已删，base/gguf/vision/ranking 四路径全失效 | 重下 |
| 27B abliteration（heretic） | ✗ 本机 | 需 bf16 + >12G | 降 8B 或租卡 |
| CUDA Toolkit（nvcc） | 不需要 | torch wheel 自带 CUDA 运行时 | — |
| pypi 直连 | ✗ | 12 s 超时 | `-i https://mirrors.aliyun.com/pypi/simple/` |
| github 直连 | ✗ | DNS 解析到非公网 IP | `hf-mirror.com` / gitee 镜像 |
| WSL/Linux 训练栈 | ✗ | 未启用 | Windows 原生 transformers+peft |

---

## 10 风险与回滚

```text
磁盘爆盘     base/merged/gguf 三者任一时最多并存两个；每阶段前查 Get-PSDrive D
显存 OOM     先降 ctx（2048→1024→512）、升 gradient_accumulation、开 gradient_checkpointing
loss NaN     99% 是 LoRA 挂到了 SSM 参数 → 检查 target_modules
模型不可用   覆盖前把旧 .ninfer 改名 .bak；起不来就删新文件、改回原名
同步目录     训练资产放同步域外（或训练期暂停同步），否则出现"文件间歇不可见"
```

---

## 11 备案包索引（复核用）

```text
_research/微调能力-备案-20261020/
├── INDEX.md          结论速查 + 复核命令（SHA256 校验 verify_bad=0）
├── 01-评估报告.md     主报告 §0–§11（完整推理链）
├── 02-EVIDENCE.md    每条结论 ↔ 命令 ↔ 原始输出
├── 03-FINDINGS.md    能力矩阵 / 路径记录 / 待办
├── 04-RUNBOOK.md     可执行命令全集（装环境→训练→合并→回炉）
├── 05-MODEL-ID.md    模型身份核实（Qwen3_5* 误读的更正）
├── probes/           8 个探针脚本（可复现）
└── data/             manifest.json（1422 bindings/733 无损/689 量化）+ quantized.csv
```

---

## 12 最短路径建议

```text
1) 只想验证链路 → 8B 基座 + QLoRA 100 步 + adapter 推理对比（半小时，不碰 27B 与回炉）
2) 要给现部署模型加能力 → 必须先解决 §8 的 1/4/5 三项（环境、基座、converter），
   其中 converter 拿不到，整条回炉链就是断的 —— 这一步先确认，别先花 54 GB 下载
3) 只想要行为改善 → 优先继续走提示层 + 数据构造（docs/03），成本远低于全链路微调
```
