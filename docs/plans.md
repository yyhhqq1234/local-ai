# 计划（两条训练线）

> **2026-11-12 结项**：9B（KittyRev-OxCoder）已交付 llama.cpp GGUF 生产；
> 27B 使用 Huihui-Swift IQ2_S（NInfer）；v6 权重误删，重建计划见 [`v6-rebuild.md`](v6-rebuild.md)。
> 本文件保留两条训练线的完整历史计划，作为重建与复盘依据。

# 计划（两条训练线）

> 合并自：PLANS.md、PLAN-OXCODER-POSTTRAIN.md、PLAN-KITTYREV-27B-GEN3.md


---

## PLANS.md

# PLANS · 计划文件索引（先读这里再开工）

> 本仓库同时跑两条完全独立的训练线。**参数、数据、磁盘区、验收口径都不通用**，
> 开工前先确认自己在哪一栏，读对应的计划文件。

| # | 训练线 | 计划文件 | 模型 | 在哪跑 | 当前状态 |
|---|---|---|---|---|---|
| 1 | **OxCoder-9B 后训练**（RE 工具路由） | [`PLAN-OXCODER-POSTTRAIN.md`](PLAN-OXCODER-POSTTRAIN.md) | Qwen3.5-9B | 本机 12G 卡（`train/lines/9b-oxcoder/out/2a-stage` 在跑） | 进行中（阶段 re / 2a-stage） |
| 2 | **KittyRev-27B GEN3**（NSFW 门控 + kitty 逆向工作台 + 保留视觉） | [`PLAN-KITTYREV-27B-GEN3.md`](PLAN-KITTYREV-27B-GEN3.md) | Qwen3.8-27B | 云端 GPU（A800 ¥7.98/h 或 RTX 5090 ¥2.88/h） | 已排期，等 GPU 与 GEN2 验收 |

## 快速区分

```text
只看 9B、只看本机、只关心 RE 工具调用参数       → PLAN-OXCODER-POSTTRAIN.md
只看 27B、只看云端、关心 NSFW 开关与视觉组件     → PLAN-KITTYREV-27B-GEN3.md
```

## 各自配套的关键文件

**OxCoder-9B 线**
```
train/lines/_shared/scripts/train_qlora9b.py · train/lines/_shared/scripts/sra_abliterate.py · train/lines/_shared/scripts/sweep_sra.py
train/lines/9b-oxcoder/out/{2a-stage,re-stage1-r2,re-stage1-r3,oxcoder9b-re-full}/
train/lines/9b-oxcoder/models/{OxCoder-9B,OxCoder-9B-sra-g1.0,mtp}/ · train/lines/9b-oxcoder/models/oxcoder-9b-Q4Q5.ninfer
train/PITFALLS.md（66 条坑 + 40 项自检，两条线共用）
```

**KittyRev-27B 线**
```
train/lines/27b-kittyrev/kitty-rev/deploy/**          云端部署与自愈（autodl_power / remote / push_base / fetch_adapter / deadline_guard）
train/lines/27b-kittyrev/kitty-rev/deploy/cloud/**   gen2_a800.sh · chain_a800.sh · finalize/quant 脚本 · 审核脚本
train/lines/_shared/scripts/local_merge_lora.py 分片级 merge（峰值 RAM<6GB）
train/lines/_shared/scripts/gsq_rco_plan.py     GSQ-RCO 配方生成（imatrix 敏感度 + 结构保护 + 预算贪心）
train/lines/_shared/scripts/local_finish_iq2s.py 本机一条链：merge→gguf→imatrix→GSQ-RCO→IQ2_S
train/lines/_shared/tools/ninfer-all-master/    tools.convert 打包器（cloud 取回，本机跑）
train/logs/gen2-run-notes.md      GEN2 全过程实测记录（§1–§25，所有数字与坑）
train/logs/a800-final/            本轮训练证据（chain / 训练 stdout / gate1 判定）
```

## 磁盘红线（两条线共用）

```text
绝不许删  ninfer-27b-kv-stream-3arch-20261019/model/Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer
          （本地主力模型）
绝不许删  ninfer-27b-kv-stream-3arch-20261019/model/qwen3.8-27b-kittyrev-v6-iq2s-mtp.ninfer（保底基线）
训练期间不动  train/lines/9b-oxcoder/models/OxCoder-9B*/ · train/lines/9b-oxcoder/out/*（OxCoder 正在跑）
可重建可删   train/lines/27b-kittyrev/merged（merge 1.9min）· train/lines/_shared/hf/datasets（HF 缓存）
```


---

## PLAN-OXCODER-POSTTRAIN.md

# PLAN — OxCoder-9B 后训练总计划（含 MTP 后训练与对齐）

> **这是执行总纲，不是日志。** 任何 agent 接手本项目时，先读本文件。
> 落盘位置：工作区根目录（`D:\BaiduNetdiskDownload\Local-AI\PLAN-OXCODER-POSTTRAIN.md`）
> 最后更新：2026-10-28 15:50 · 状态：**2B 改为带开关训练**（训练集 22,197 条 + val 85 / test 129 门控集已生成，零重叠校验 PASS；2A 完成后按 §5.3 开跑）

---

## 0 现状快照（已核对，勿重复验证）

### 0.1 基座

| 项 | 值 |
|---|---|
| 模型 | `OrionLLM/OxCoder-9B`（Apache-2.0，基座 Qwen3.5-9B） |
| 本地路径 | `train/lines/9b-oxcoder/models/OxCoder-9B`（18.8 GB bf16，760 张量） |
| 架构 | `Qwen3_5ForConditionalGeneration`，32 层（24 linear_attn + 8 full_attn） |
| 维度 | hidden 4096 / intermediate 12288 / 16 heads / 4 kv / head_dim 256 / vocab 248320 |
| 上下文 | 262,144 原生 |
| MTP | config 声明 `mtp_num_hidden_layers: 1`，但权重 **mtp = 0**（已单独落盘，见 0.4） |
| 能力基线 | SWE-bench Verified **73.5** / Terminal-Bench 2.1 **49.6** / HLE 21.2 |

### 0.2 训练数据（全部就绪）

| 数据集 | 路径 | 条数 | 用途 |
|---|---|---|---|
| **kitty 逆向核心** | `train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl` | **5602** | RE 能力主数据 |
| **agent 轨迹 8K** | `train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-8k.jsonl` | 1500 | 工具编排形状 |
| agent 轨迹 8K | `train/lines/9b-oxcoder/data/agent-traj/swe-rebench/rebench-8k.jsonl` | 150 | Claude Code 真迹 |
| agent 轨迹 8K | `train/lines/9b-oxcoder/data/agent-traj/deepswe/deepswe-8k.jsonl` | 113 | 30B 思考链 |
| **agent 轨迹 16K** | `train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-16k.jsonl` | 500 | 长上下文档 |
| **NSFW 训练集** | `train/lines/_shared/data/nsfw/train-{cont,scene,multi,style,expand}.jsonl` | **13668** | NSFW 生成能力 |
| NSFW 总词表 | `train/lines/_shared/data/nsfw/nsfw-glossary-merged.jsonl` | **283** | 词表 SFT |
| NSFW 结构化词表 | `train/lines/_shared/data/nsfw/nsfw-lexicon-v9.json` | 470 词 / 12 类 | 训练参考（不直接喂） |

合计可直接训练样本：**5602 + 2263 + 13668 = 21,533 条**

**验证集 / 测试集（额外生成，训练集零改动）**

| 集 | 轨迹 | NSFW 词表题 | 中文探针 | 合计 | 说明 |
|---|---|---|---|---|---|
| `train/lines/9b-oxcoder/data/eval/val/` | 73 | 60 | 20 | **153** | Nemotron/DeepSWE 未用过样本 + lexicon 排除 train 283 词后的池 |
| `train/lines/9b-oxcoder/data/eval/test/` | 97 | 60 | 20 | **177** | 同上，与 val 不同的样本 |

生成脚本：`train/lines/_shared/scripts/build_val_test.py`（生成）+ `verify_eval_sets.py`（重叠校验 + MANIFEST）
注意：val/test 轨迹用 `ctx 8192` 生成（DeepSWE 的 user 部分约 3600 token，ctx 4096 时会被大量过滤 —— 实测只留 16 条）。

### 0.3 已有产物

| 产物 | 路径 | 状态 |
|---|---|---|
| SRA 去审查 merged | `train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0`（18 GB） | ✅ 可作训练起点 |
| Heretic 去审查 LoRA | `train/lines/9b-oxcoder/models/OxCoder-9B-abl-lora`（170 MB） | ✅ 备选 |
| 第 1 代 RE adapter | `train/lines/9b-oxcoder/out/oxcoder9b-re-full/` | ✅ checkpoint-176 含 optimizer 可续训 |
| **★ RE 基线（r2，2026-10-28）** | `train/lines/9b-oxcoder/out/re-r2-ckpt1400-snapshot`（173 MB） | ✅ **RE 定档**：2 遍数据 / 泛化命中 **91.7%** / 编造 **0** / L3 4/4 |
| RE r2 final（3 遍，已否决） | `train/lines/9b-oxcoder/out/re-stage1-r2/final`（173 MB） | ⚠ 泛化 83.3% < 91.7%，**负增益**，保留备查 |
| **★ v3 数据集（2026-10-28 P1）** | `train-kitty-v3-merged.jsonl`（23,718）/ `train-kitty-v3-bucketed.jsonl`（7 桶） | ✅ **r3 用**：v2 + 格式归一化 2526 + 零样本 action 639；(工具,action) **195/195** |
| v2 增广数据集（已被 v3 取代） | `train-kitty-v2-aug.jsonl`（23,079）/ `-bucketed`（16 桶） | ⚠ 保留备查：core 5602 + 覆盖补强 149，增广 4x |
| **★ 参数修复诊断（2026-10-28 P0）** | `train/lines/9b-oxcoder/out/diag-tier3-40cases-args.json` | ✅ 4 档 × 40 条 × 含 `resp` 原文 / `expect_args` / `missing` |
| **★ 泛化评测器（2026-10-28）** | `train/lines/_shared/scripts/eval_re_generalize.py` | ✅ 12 条改写提问 / 无工具名 / L1-L3 / 四分类；**主判据** |
| **★ checkpoint 选优器** | `train/lines/_shared/scripts/select_best_ckpt.py` | ✅ 遍历 ckpt 跑泛化集，按「编造升序→命中降序→step 升序」排名 |
| **★ RE 阶段 adapter（2026-10-28）** | `train/lines/9b-oxcoder/out/re-stage1-fixed/final`（173 MB） | ✅ **P2 实际起点**：1401 步 / loss 1.11 / 编造工具 6→1 |
| **★ 分桶训练数据（5 份）** | `*-bucketed.jsonl` | ✅ 见 §5.5 |
| **★ NSFW 门控训练集（2026-10-28）** | `train/lines/9b-oxcoder/data/nsfw-gated/train-2b-gated.jsonl`（22,197 条） | ✅ 2B 用：正 6,999 / 负 13,998 / 常规对照 1,200 |
| **★ 门控评测器** | `train/lines/_shared/scripts/nsfw_gate_eval.py` | ✅ 三探针（TRIGGER/NOGATE/GENERAL+TRAP）+ 固定集模式，阈值见 §9.1 探针 7 |
| **★ 门控 val/test 集（2026-10-28）** | `train/lines/9b-oxcoder/data/eval/val/nsfw-gate.jsonl`（85）/ `test/nsfw-gate.jsonl`（129） | ✅ 与训练集零重叠、on/off 成对、触发词 9/9 覆盖 |
| **MTP 权重** | `train/lines/9b-oxcoder/models/mtp/qwen3.5-9b-mtp.safetensors`（464 MB / 15 张量） | ✅ 已落盘 |
| GSQ 论文级量化 | `train/lines/27b-kittyrev/quant/gsq_gumbel.py` + `run_convert_gsq.py` | ✅ 实测 Q4 误差 −8.88% |
| MTP 后训练脚本 | `train/lines/27b-kittyrev/quant/mtp_posttrain.py` | ✅ 自测 loss 降 84% |
| MTP 拼装脚本 | `train/lines/_shared/scripts/attach_mtp.py` | ✅ 支持 `--src/--extract-only/--verify-only` |

### 0.4 硬件与依赖（**2026-10-28 实测修正**）

| 项 | 值 | 注意 |
|---|---|---|
| GPU | RTX 5070 Ti Laptop **12227 MiB（11.91 GiB）** | 训练时 alloc 7.62 / reserved 9.41 / free 1.02+ GiB |
| RAM | 32 GB | `low_cpu_mem_usage=True` 后加载只占 10.3 GB |
| torch | 2.9.1+cu130 | ⚠️ 但**未编译 flash attention** |
| transformers / trl / peft / bnb | 5.20.2 / 1.16.0 / 0.21.2 / 0.50.2 | ✅ |
| triton-windows / liger-kernel | 3.8.0.post29 / 0.8.5 | ✅ liger 官方集成不支持 Qwen3_5，已手写 Trainer |
| **flash-linear-attention** | **0.6.0** | ✅ **已装且已生效**（旧版写"未装"是错的） |
| `causal_conv1d` | ❌ 装不上（无 nvcc/MSVC） | 走 PyTorch 回退，慢但正确 |
| `flash-attn` | ❌ PyPI 无 Windows 轮子 | head_dim=256 也让 cuDNN attention 拒绝（>128） |
| **★ ctx 硬上限** | **4096** | 8192 时 reserved 25.98 GiB 超物理 → WDDM 换页 → 1149 s/步；9216 OOM |
| **★ ga 上限** | **4** | **ga=16 必卡死在第 1 步之后**（连续 3 次复现，与 optimizer 无关） |
| **★ 显存峰值** | alloc **7.622 GiB** 恒定 | 修复前 11.7 GiB 贴线 + 碎片累积 → 掉速 30 倍 |

---

## 1 目标与验收口径

### 1.1 目标

| 能力 | 目标 | 验收探针 |
|---|---|---|
| **RE（逆向）** | 工具编排正确率 ≥ 基线 | kitty 探针集（判据式回答） |
| **长上下文工程** | ctx 8192 下跨文件追踪可用 | 5 类长上下文探针（见 §6.2） |
| **NSFW 生成** | 词表命中率、风格一致性 | 词表覆盖 + 人工抽检 |
| **行为对齐** | 判据式回答 / 工具调用格式 | 格式合规率 ≥ 95% |
| **安全边界** | 域内生成、越界拒答 | 拒答率双档（域内 ≤5%、越界 ≥90%） |
| **MTP 投机解码** | 接受率 ≥ 40% | 引擎 accept_rate |

### 1.2 明确不做的事

```
✗ 不碰 27B（4bit 12.59 GiB > 10.2 GiB 可用，8 条 offload 路径全部实测失败）
✗ 不改 vendor converter 源码（走 run_convert_gsq.py 运行时注入）
✗ 不用 bf16 全量训练（12 GB 装不下 18.8 GB 权重）
✗ 不混训 RE + NSFW（第 2 代 joint 混训在 172/516 步 BSOD 0x1E，已验证教训）
```

### 1.3 铁律①：训练必须拉起监控子 agent（硬性，不可跳过）

```
【规则】任何一次模型训练（train / 后训练 / MTP 对齐 / 量化校准 / 重跑）启动，
       必须在训练进程起来的同一时间拉起一个专职「训练监控子 agent」。
       没有监控子 agent 在跑 = 训练视为未启动，主 agent 不得进入下一步。
```

| 项 | 要求 |
|---|---|
| **触发条件** | 任何 `python train*.py` / `run_train*.ps1` / trl Trainer / MTP 重训 / 量化误差校准启动 |
| **拉起时机** | 训练进程启动**之前或同一时刻**，不得训练跑了几百步才补监控 |
| **子 agent 职责** | ① 盯 loss/学习率/步速/显存 alloc·reserved/GPU 温度与功耗 ② 读训练日志尾部与 `train/logs/` ③ 主动找 bug：NaN·Inf loss、loss 平台期/突刺、步速掉档（正常 ~4.5 s/步，掉到 100 s+/步 即 WDDM 换页）、OOM 前兆、checkpoint 写坏、数据侧格式错（截断/空样本/工具名编造）④ 判定是否需人工干预 |
| **汇报节奏** | **每 10 分钟一次**，固定格式：`[MONITOR HH:MM] step=N loss=X lr=Y 步速=Zs/step 显存=alloc/reserved GiB 判定=绿/黄/红 + 一句结论` |
| **即时上报（不等 10 分钟）** | 出现 NaN/Inf、OOM、进程退出、步速掉 5 倍以上、loss 突刺 >2 倍、checkpoint 缺失 → 立即告警并给可执行处置建议（降 ctx / 降 ga / 重启 / 回滚 checkpoint） |
| **收尾** | 训练结束或中止时出一份监控小结（步数曲线要点 + 异常清单 + 建议下一步），落 `train/logs/monitor-<ts>.md` |
| **禁止** | 不许主 agent 一边训练一边自己兼监控（分不清责任）；不许"等跑完再说"；不许只看 stdout 不看显存与步速 |

子 agent 的产出只作监控与判定，**不改训练超参**；需要改配置一律回到主 agent 决策。

---

## 2 阶段总览

```
P0 环境准备            ~1 h      装 causal_conv1d/liger，建混合数据集
P1 去审查确认          ~0（已有） 复用 sra-g1.0；必要时重跑
P2 主训练（三阶段）    ~6-12 h   2A RE+轨迹 → 2B NSFW → 2C 长上下文
P3 merge + 冒烟        ~1 h      bf16 merge，pin architectures，四探针冒烟
P4 MTP 后训练          ~1 h      拼装 → 对齐重训 → 接受率对比
P5 量化 + 部署         ~1 h      GSQ 量化 → .ninfer → 引擎验证
P6 评估与对齐验收      ~2 h      六类探针 + 回归 + 对齐判定
```

**总预算：约 12-18 小时机器时间，跨 2-3 个工作日。**

---

## 3 P0 环境准备（前置，必做）

### 3.1 装缺失依赖（**2026-10-27 22:13 实测结果已更新**）

```powershell
# ① 确认引擎已停（腾显存）
nvidia-smi --query-gpu=memory.used --format=csv   # 期望 < 2000 MiB

# ② triton-windows（liger 的运行底座）—— ✅ 已装
train\.venv\Scripts\pip.exe install triton-windows        # → 3.8.0.post29 (cp313 win_amd64)

# ③ liger-kernel —— ✅ 已装（必须 --no-deps，否则 pip 解析不到 Linux 的 triton 包）
train\.venv\Scripts\pip.exe install --no-deps liger-kernel  # → 0.8.5

# ④ causal-conv1d —— ❌ 装不上（见下）
train\.venv\Scripts\pip.exe install causal-conv1d
```

**实测结论（2026-10-27 22:13）**

| 依赖 | 结果 | 影响 |
|---|---|---|
| `triton-windows` | ✅ 3.8.0.post29 | liger 底座就绪 |
| `liger-kernel` | ✅ 0.8.5，`fused_linear_cross_entropy` op 可 import | **但 transformers 集成不支持 Qwen3_5**（39 个支持模型里 Qwen 只有 `qwen2vl_mrope`）→ `SFTConfig(use_liger=True)` 走不通 |
| `causal-conv1d` | ❌ 失败 | 无 `nvcc`/MSVC；且 build isolation 会拉 `torch 2.14.1`（与现有 2.9.1+cu130 冲突） |
| `flash-linear-attention` | ❌ 未装 | Qwen3.5 的 `chunk_gated_delta_rule` 回退 PyTorch 参考实现（**慢但正确**） |

**已完成的绕过（2026-10-27 23:30）**

| 问题 | 解法 | 效果 |
|---|---|---|
| liger 集成不支持 Qwen3_5 | 手写 `LigerSFTTrainer`（`train/lines/_shared/scripts/liger_ce.py`）：不调 `model(**inputs)`，直接调 text model 拿 `last_hidden_state`，再手写 chunked CE（chunk=1024） | selftest：loss 差 **9.5e-07**，CE 显存 **5102 → 509 MiB（省 90%）** |
| `prepare_model_for_kbit_training` 把 lm_head/embed 转 fp32（各 3.79 GiB） | 加载后把这两个冻结大表转回 bf16（仅 `--use-liger-ce` 时） | 加载后 allocated **10.91 → 7.36 GiB（省 3.55 GiB）** |

**等价路径（已采纳）**

| 原计划 | 替代方案 | 代价 |
|---|---|---|
| `packing=True`（需 causal_conv1d） | **保持 `packing=False`** | 不能把短样本拼长；kitty 侧 p50 仅 172 token，窗口利用率低 |
| `use_liger=True` 省 logits 显存 | **降 ctx 到硬件算力允许的范围**（见下表） | ctx 上限从 8192 降到 **4096** |
| 想要 8192 | 需手接 `liger_kernel.ops.fused_linear_cross_entropy` 到 trainer 的 `compute_loss`（~50 行自定义 Trainer） | +30 分钟工作量 |

**ctx 上限推导（4bit QLoRA + gc on + packing=False + 无 liger op）**

```
固定开销：4bit 权重 5.0 GiB + LoRA/梯度/8bit优化器 0.15 GiB
激活（32 层）：ctx 2048→1.2 / 4096→2.3 / 8192→4.5 GiB
logits（无 fused CE）：ctx × 248320 × 2B
   ctx 2048 → 1.0 GiB
   ctx 4096 → 2.0 GiB
   ctx 8192 → 4.07 GiB
─────────────────────────────────────────
ctx 2048 → 7.35 GiB  ✅
ctx 4096 → 9.45 GiB  ✅  ← 当前上限
ctx 8192 → 13.6 GiB  ❌ OOM
```

→ **P2 各阶段 ctx 统一用 4096**（原计划 8192 下调）；要 8192 先做 liger CE 接入。

> **2026-10-28 实测更新（修 version）**：上面的显存推导是**修复前**的估算，已被实测推翻：\
> · 真实 alloc 是 **7.622 GiB**（不是 7.35/9.45），因为 fp32→bf16 全量转换 + 卸载视觉塔\
> · ctx 4096 实测可用（RE 阶段 1401 步跑通，2.5 s/步）\
> · ctx 8192 不是 OOM 而是**换页**（reserved 25.98 GiB 超物理 11.91 → 1149 s/步）\
> · **ga 上限是 4，ga=16 必卡死**\
> 完整实测数据与 4 项修复见 **§5.0**；坑清单见 `train/PITFALLS.md`。

### 3.2 建三个训练集（一次性生成）

```powershell
# 2A：RE + 轨迹（7:3）
python -c "
import json, random
random.seed(1337)
kitty=[l for l in open('train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl',encoding='utf-8')]
traj=[l for f in ['train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-8k.jsonl',
                  'train/lines/9b-oxcoder/data/agent-traj/swe-rebench/rebench-8k.jsonl',
                  'train/lines/9b-oxcoder/data/agent-traj/deepswe/deepswe-8k.jsonl']
      for l in open(f,encoding='utf-8')]
k=int(len(traj)*7/3)
mix=random.sample(kitty,min(k,len(kitty)))+traj
random.shuffle(mix)
open('train/lines/9b-oxcoder/data/_legacy/mix-re-traj-8k.jsonl','w',encoding='utf-8').writelines(mix)
print('2A:',len(mix),'条（kitty',min(k,len(kitty)),'+ traj',len(traj),'）')
"

# 2B：NSFW（直接拼 5 分片）
cat train/lines/_shared/data/nsfw/train-*.jsonl > train/lines/9b-oxcoder/data/_legacy/mix-nsfw-all.jsonl
# 追加词表 SFT
cat train/lines/_shared/data/nsfw/nsfw-glossary-merged.jsonl >> train/lines/9b-oxcoder/data/_legacy/mix-nsfw-all.jsonl

# 2C：长上下文（16K 轨迹 + kitty 混）
python -c "
import json, random
random.seed(1337)
k=[l for l in open('train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-core.jsonl',encoding='utf-8')]
t=[l for l in open('train/lines/9b-oxcoder/data/agent-traj/nemotron-swe/swe-16k.jsonl',encoding='utf-8')]
mix=random.sample(k,min(len(t)*3,len(k)))+t
random.shuffle(mix)
open('train/lines/9b-oxcoder/data/_legacy/mix-longctx-16k.jsonl','w',encoding='utf-8').writelines(mix)
print('2C:',len(mix),'条')
"
```

**判据**：
- `mix-re-traj-8k.jsonl` ≈ 7500 条（kitty 5287 + traj 2263）
- `mix-nsfw-all.jsonl` = 13668 + 283 = **13951** 条
- `mix-longctx-16k.jsonl` ≈ 2000 条（kitty 1500 + 16K 轨迹 500）

---

## 4 P1 去审查确认

**已有产物可直接用**：`train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0`（SRA：Surgical Refusal Ablation，arXiv 2601.08489，KL 0.016-0.044）

| 检查项 | 命令 | 期望 |
|---|---|---|
| 权重完整 | `ls train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0/model-*.safetensors \| wc -l` | 与 config 的 shard 数一致 |
| 架构正确 | `python -c "import json;print(json.load(open('train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0/config.json'))['architectures'])"` | `['Qwen3_5ForConditionalGeneration']` |
| 可加载 | transformers `from_pretrained` 试加载（meta device） | 无异常 |

**若 SRA 产物有问题**，回退方案：用 `load_in_4bit` + Heretic LoRA（`OxCoder-9B-abl-lora`）在训练时 fuse。

---

## 5 P2 主训练（四阶段，2026-10-28 全量实测后重写）

> **本节的参数全部来自实测，覆盖 2026-10-27 的估算版本。**
> 旧版结论（ctx 8192 需 200s/步、ga=16 可用、2A 需 11-14h）已被推翻，原因见 §5.0。

### 5.0 通用配置（每个阶段都必须带，缺一项就出问题）

```bash
# 环境变量（两个都必须）
PYTORCH_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.80
VRAM_FRAC=0.93

# 命令行必带
--ga 4              # ★ 绝不用 16：实测 ga=16 必卡死在第 1 步之后
--optim adamw_torch # paged_adamw_8bit 在 Windows 上同样会卡
--use-liger-ce      # 省 logits（ctx 4096 时省 2 GiB，ctx 9216 时省 4.58 GiB）
--save-total-limit 8
-u                  # Python 不缓冲，否则日志几十/上百分不更新
```

**抗记忆化必带（2026-10-28 新增，r2 实测教训）**：

```bash
--lora-dropout 0.10   # r2 是 0.05；直接对抗记忆化（新参数，2026-10-28 加）
--weight-decay 0.01   # r2 是 0；抑制大权重（新参数）
--epochs 1            # 2 遍就开始背答案，见下
```

**为什么是 1 epoch**（r2 实测，同一批 5602 条）：

| 数据遍历 | 泛化命中 | in-sample n-gram 重合 | 逐字复现参考答案 |
|---|---|---|---|
| 1 遍 | 50.0% | 0.167 | 1 条 |
| **2 遍** | **91.7%** | 0.515 | 4 条 |
| 3 遍 | 83.3% | 0.478 | 4 条 |

第 3 遍是**负增益**（83.3% < 91.7%）。增广后 1 遍能见到 4 倍表述多样性，
不需要靠多遍来"加深印象"。

**验收口径（2026-10-28 修正，勿回退）**：

- ❌ 不用 train loss 判好坏 —— r2 的 loss 最低点 `final`（0.3731）泛化**最差**
- ❌ 不用 in-sample 命中率 —— 三档全打平（都 5/6），只反映记忆强度
- ✅ 用 `eval_re_generalize.py`（12 条改写提问、无工具名）：命中率 + 编造数 + L3 命中
- ✅ 用 `eval_re_heldout.py` 的 **n-gram 重合**作为记忆度指标（<0.40 健康，>0.60 停）
- ✅ 训练后用 `select_best_ckpt.py` 遍历 ckpt 选优，不靠 loss 猜

**评测侧三条硬约束（2026-10-28 加，完整规程见 `train/EVAL-PROTOCOL.md`）**：

```bash
① 所有评测脚本先调 gpu_guard.apply()   # VRAM 0.88 上限 + CPU 6 线程 + BelowNormal
② --batch 保持 1（实测 batch=4 有 3/36、batch=8 有 1/8 关键信息不同，会改结论）
③ max_new 保持 300（压了会截断参数 → 制造假 noarg → 降质量）
```

评测结果按「场景库 md5 + adapter 指纹 + max_new」缓存到 `train/lines/9b-oxcoder/out/eval-cache/`：
重跑同一档**约 10 秒**（首次 4 档 × 40 条约 100 分钟）；改场景库或换 adapter 自动失效。

**判据口径（40 条 = 36 正向 + 4 负向）**：命中率（**工具 + 参数都对**）≥45% · 编造 ==0 ·
参数错 ≤8 · 负向题 ≥3-of-4。只判工具名的 36 条口径仅用于粗筛（≥75%）。

**训练脚本已内置的 4 项修复（不要回退）**：

| # | 修复 | 作用 |
|---|---|---|
| 1 | 全量 fp32 → bf16（179+ 个参数，不只大表） | forward **6.616 → 1.144 s（5.8×）** |
| 2 | 卸载视觉塔 `model.model.visual = None` | 省 0.23 GiB |
| 3 | `set_per_process_memory_fraction(VRAM_FRAC)` | 防 WDDM 换页拖垮系统 |
| 4 | 训练前 `reset_peak_memory_stats()` | peak 不被加载峰值污染 |

**数据必须按长度分桶**（`train/lines/_shared/scripts/bucket_by_length.py`），否则第 48 步起碎片累积、掉速 30 倍。

**实测速度基准**：

| 样本长度 | 单样本时间 | 来源 |
|---|---|---|
| 270 token（kitty 均值） | **0.72 s** | RE 阶段 1401 步实测 |
| 1590 token（2A 均值） | **≈4.3 s** | 按 2.7 ms/token 推算 |
| 4096 token（满 ctx） | **47 s** | hidden-only 基准 |

**ctx 决策**：**统一 4096**（不是旧版说的 2048/8192）。
- ctx 4096 是 12 GB 卡的硬上限（8192 时 reserved 25.98 GiB 超物理 → WDDM 换页 → 1149 s/步；9216 直接 OOM）
- kitty / NSFW 数据 p99 远低于 4096，用 2048 更快，可单独下调

---

### 5.1 RE 阶段 — kitty 工具编排（r1 / r2 完成，**r3 定档 + 10-31 方案 Z 补强**）

> **✅ 2026-10-31 更新**：方案 Z 的 B 腿在 r3 之上补了「调用范式」数据，得到更强成品：
> `train/lines/9b-oxcoder/out/z-re-v4/final` = r3 + 7000 主力 + 600 调用范式 + 8 反编造（1902 步 · lr 2e-5）
> 成绩：hit 30/40 · acc 75.0% · **编造 0** · wrong 6（优于 r3 的 7）· noarg 4 → **PASS**
> 详见 `train/logs/z-final-report.md` 与 `TASKPOINT.md §A11`。r3 仍保留作基线与对照。

#### 轮次记录（全部实测 · 四份口径并存）

| 轮 | 数据 | 遍数 | train_loss | 命中 12 条 | 命中 36 条 | **命中 40 条** | **参数错** | 编造 | 备注 |
|---|---|---|---|---|---|---|---|---|---|
| r1 `re-stage1-fixed/final` | core 5602 | 1 | 1.110 | 50.0% | 58.3% | 27.5% | 14 | 1 | 旧参数最优 |
| r2 `re-r2-ckpt1400-snapshot` | core 5602 | 2 | ≈0.51 | 91.7% | 69.4% | 22.5% | 20 | 1 | — |
| r2 `re-stage1-r2/final` | core 5602 | 3 | 0.3731 | 83.3% | 75.0% | 25.0% | 21 | 1 | 旧工具最优（已被超越） |
| **r3 `re-stage1-r3/final`** | **v3-bucketed 23718** | **1** | **0.7253** | — | — | **75.0%** | **3** | **0** | **★ 新定档：四维全优** |

**★ 定档结论被修正过三次，四份口径的演进（详见 `train/RE-BASELINE.md` §2.3 / §2.4 / `train/R3-ACCEPTANCE.md`）**：

| 口径 | 排序 | 结局 |
|---|---|---|
| 12 条（只判工具名） | 档2 91.7% > 档3 83.3% | 被 36 条推翻（1 条之差 = 8.3 pt，纯噪声） |
| 36 条（只判工具名） | 档3 75.0% > 档2 69.4% > 档1 58.3% | 被 40 条推翻（**漏了参数维度**） |
| 40 条（工具 + 参数 + 负向题） | 档1 27.5% > 档3 25.0% > 档2 22.5% | **被 r3 推翻（同口径下 r3 = 75.0%）** |
| **40 条 + v3 数据（r3）** | **r3 75.0% / 参数错 3** | **★ 当前采用** |

**40 条口径暴露的真问题**：工具选对但**参数填错** = 档1 14 / 档2 20 / 档3 21 条。
36 条的 75% 与 40 条的 25% 之间那 50 个百分点，全部是参数错。

**当时的误判**：以为「参数能力随训练遍数倒退」（14→20→21）= 参数记忆化，
于是把 r3 目标定为「补参数样本」。**P0 诊断（2026-10-28）推翻了这个判断**：

```text
21 条参数错里 18 条是「值写对了，但用文档枚举句式」
  resp 原文：`kitty_die — action 取 scan：`      ← 不是 `action=scan`
  根因：训练集 5811 条里 632 条（10.9%）是这种句式，涉及全部 64 个工具
  模型是忠实模仿训练集格式，不是不知道 action 值
```

**真正的解法是数据格式归一化 + action 覆盖补全**，不是加参数样本、更不是加训练遍数：

| 修复（P1） | 内容 | 效果 |
|---|---|---|
| P1-b 格式归一化 | 2526 条 assistant 首行改成 `工具 action=X`（内容一字不删，多值枚举保留在括号里） | 18 条假参数错直接清零 |
| P1-a 零样本 action | 71 个从未出现过的 action 补 639 条（3 语域 × 3 过采样） | (工具,action) 覆盖 124/195 → **195/195** |

**r3 实测证明**：1 遍、loss 0.7253（比 r2 的 0.3731 高，但是健康的）、
参数错 **3**、命中 **75.0%**、编造 **0**、负向 **4/4**。
**r2 多训 2 遍把参数错从 14 做到 21；r3 只训 1 遍、换了数据，参数错降到 3。**

**负向题（N01-N04）三档全对，r3 保持 4/4**，基座 3/4 错
—— 说明「该不该调工具」早就学会了，「怎么填参数」是数据格式问题，不是能力问题。

**因此 r3 的目标改变**：不是「提工具路由」（已 75%），而是**补参数填充**（40 条口径仅 25%）。

#### 核心教训：train loss 不能当验收标准

r2 训练时 train loss 从 0.6907 降到 0.3731（-46%），但泛化命中率是
**1 遍 50% → 2 遍 91.7% → 3 遍 83.3%**。**loss 最低的 final 反而最差。**

原因：`eval_re_heldout.py` 从训练集抽样（只跳过头 20 条），是 in-sample 测试。
三档在它上面全打平（都 5/6），只有 n-gram 重合从 0.167 涨到 0.515、逐字复现条数从 1 涨到 4，
暴露出训练遍数越多背得越牢。详见 `train/RE-BASELINE.md` 与 PITFALLS E4。

**主判据 = `train/lines/_shared/scripts/eval_re_generalize.py`**：12 条改写提问、全程无 `kitty_` 提示、
L1/L2/L3 三档难度、四分类评分（hit / wrong / fake / none）。

```
命中率 >= 70%（12 条里 >= 9 条）
编造 == 0
L3 命中 >= 2/4
```

#### r3 配方（**已完成，2026-10-29 02:20** · 实测配置）

```powershell
# 前置数据（已就绪）：
#   train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-merged.jsonl     23718 条 = 格式归一化 23079 + 零样本补强 639
#   train/lines/9b-oxcoder/data/kitty-reverse/train-kitty-v3-bucketed.jsonl   同上，128 token 分桶（7 桶）

$env:PYTORCH_ALLOC_CONF="max_split_size_mb:64,garbage_collection_threshold:0.80"
$env:VRAM_FRAC="0.93"

train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py `
  --base train\lines\9b-oxcoder\models\OxCoder-9B `
  --data train\lines\9b-oxcoder\data\kitty-reverse\train-kitty-v3-bucketed.jsonl `
  --stage re --out train\lines\9b-oxcoder\out\re-stage1-r3 `
  --ctx 2048 --bs 1 --ga 4 `
  --epochs 1 --lr 3e-5 `
  --lora-dropout 0.10 --weight-decay 0.01 `
  --optim adamw_torch --use-liger-ce `
  --save-steps 200 --save-total-limit 8
```

**参数依据**：

| 参数 | r2 | r3 | 依据 |
|---|---|---|---|
| `--epochs` | 2 | **1** | 2 遍 = 91.7%，3 遍 = 83.3%（负增益）；v2 已含 4 倍表述多样性 |
| `--lr` | 5e-05 | **3e-05** | 续训起点 loss 已 0.69，5e-5 偏高 |
| `--lora-dropout` | 0.05 | **0.10** | 直接对抗记忆化（新参数） |
| `--weight-decay` | 0 | **0.01** | 抑制大权重（新参数） |

数据 23718 条 / ga 4 = **5930 步**，× 2.11 s ≈ **3.4 h**。

#### r3 数据相对 r2 的五项改进

| 改进 | 效果 |
|---|---|
| user 提问同义改写增广（K=4） | 表述多样性 **4.03x**，逼模型学「语义 → 工具」而非字面命中 |
| 工具覆盖补强 149 条 | `<50 覆盖` 的工具从 **34 个 → 0 个**；pchain/dualview/acescan 用 `--force` 强制补 |
| 修正 4 处工具名错拼 | `kitty_c`→`kitty_ce`、`kitty_ace`→`kitty_acescan`、`kitty_adb`→`adb` |
| **★ assistant 首行格式归一化 2526 条** | 文档句式 `工具 — action 取 A/B/C` → 可执行 `工具 action=A`；内容一字不删。P0 实测 21 条参数错里 **18 条是这个格式问题**，不是值错 |
| **★ 零样本 action 补强 639 条** | (工具,action) 覆盖 **124/195 → 195/195**；`kitty_settings` 8 个、`kitty_selftest` 4 个、`kitty_dualview`、`kitty_inject` 3 个等 71 个从未出现过的 action 全部补上 |

#### §5.1.1 r3 数据升级依据（2026-10-28 P0/P1）

详见 **`train/PARAM-FIX.md`**。三条核心实测：

```text
① gpu_guard 不改结果：档3 40 条重跑，kind 逐条一致 40/40
   → 后续评测一律带 guard，防卡顿与可复现不冲突

② 21 条「参数错」里 18 条是格式问题
   resp 原文：`kitty_die — action 取 scan：`（值对，格式不可执行）
   训练集 core+coverage 5811 条里 632 条（10.9%）是这种句式，涉及全部 64 工具

③ 71 个 action 零样本，长尾断崖
   凡出现过的 (工具,action) 样本数都 ≥3，没出现过的就是 0
```

#### 训练后必做的选优（不靠 loss 猜）

```powershell
train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\select_best_ckpt.py --run train\lines\9b-oxcoder\out\re-stage1-r3
```

遍历所有 `checkpoint-*`，逐个跑 12 条泛化题，按「编造升序 → 命中率降序 → step 升序」排名，
直接给出最优 checkpoint 与采用命令。

**语义整点（epoch 边界、整千步）训练中必须手工快照** —— r2 实测 `save_total_limit=8`
会把 `checkpoint-1400` 轮转删掉（见 PITFALLS C4）。

#### 已知弱点（r3 目标）

| 条目 | 现象 | 处置 |
|---|---|---|
| G06 多跳反查 | r1/r2 三档全给 `kitty_ce`（应 `kitty_pchain`） | v2 已补 5 条明确表述 + 增广到约 20 条 |
| G09 三视图分叉 | r2 档2 对、档3 错（给 `kitty_km,kitty_prot`） | 3 遍数据退化的证据；r3 只跑 1 遍即可规避 |

#### r1 首轮实测（留档）

| 项 | 值 |
|---|---|
| 数据 / 步数 | kitty core 5602 条（64 token 桶）/ 1401 步 |
| 耗时 | **3397 s（56.6 min）** |
| train_loss | 1.1102（末步 0.8186） |
| 速度 / 显存 | 2.13–2.42 s/步；alloc 7.622 / reserved 9.41 / free 最低 1.024 GiB |
| 产物 | `train/lines/9b-oxcoder/out/re-stage1-fixed/final`（173 MB） |

**验收（旧口径，已被 §5.1 新判据取代）**：真编造 6 → 1（-83%）；
三段式结构逐字学会；工具调用格式正确。**注意：该结论基于 in-sample 测试，不可作为最终验收。**

---

### 5.1b RE 训练方法 V2 —— 候选工具集 + 硬负例（**2026-11-03 定稿，待跑**）

> **为什么要有这一节**：V1（纯 SFT「问句→唯一答案」）四轮加数据实测 30 → 29 → 30 → 29，净收益 ≤0。
> 诊断与实测见 `TASKPOINT.md §A20`：不是数据量问题，是**训练信号形态问题**。
> 本节是可直接执行的 V2 规格，数据已生成（见 5.1b.2）。

#### 5.1b.1 三条实测证据（V1 的病灶）

```text
① A/B 实验（train/logs/ab-schema-40.json）：
   同一模型 z-re-v4，40 题，只换 system
   A 无工具清单 30/40 (75.0%)  |  B 加 64 工具紧凑清单 29/40 (72.5%)
   结构分化：L3 +2、参数错 −2，但 L1 −2、选错 +3
   ⇒ 「缺 schema」不是主因；加信息不加分，说明瓶颈在「会不会在一堆候选里排除干扰」

② 换 system 就翻转 11 条（5 好 6 坏）⇒ 模型没有稳定的「任务语义→工具」映射，靠表面模式

③ 部署要面对 19,991 字符完整 schema（≈10,000 token），而训练/评测 system 只有 115 字符、
   ctx 只有 2048 ⇒ 75% 是乐观值，不是部署值
```

#### 5.1b.2 V2 数据（已生成，可直接训练）

```text
生成器  train/lines/_shared/scripts/build_re_candidates.py
产物    data/kitty-reverse/mix-z-re-v2-cand-train.jsonl   7562 行（seed 42，训练用）
        data/kitty-reverse/mix-z-re-v2-cand-eval.jsonl    7562 行（seed 7，评测用，采样更硬）
质检    _work/qc_candidates.py → 信号矛盾 0 行 · 非法候选 0 · 判定「可直接训练」

样本形态变化（只改 system，user/assistant 原样不动）：
  V1 system = 115 字符（无工具定义）
  V2 system = 115 字符 + 「当前会话可用工具（只能从下列工具中选）」+ 8~14 个工具定义
             每条形如  - kitty_die: packer/compiler 检测（DIE）  actions=[scan,status]

候选集构成（硬负例优先，CLUSTERS 手工定义 11 个易混簇）：
  ① 必含 expect 里的全部正确工具
  ② 同簇易混工具（如 kitty_dbg 与 kitty_x64dbg/kitty_dualview；kitty_rea_* 十个同族）
  ③ 同通道近邻   ④ 少量跨通道
  负向样本（27.1%，assistant 本就不调工具）：候选集给「看起来相关」的工具，正解=不调用

长度实测：P50 1176 / P99 1955 / Max 3926 字符
  >2048 字符 58 行（0.77%）· >4096 字符 0 行
  ⇒ ctx 4096 可 100% 覆盖
```

#### 5.1b.3 ctx 4096 可行性（2026-11-03 实测，已跑通）

```text
试跑   out/_ctx4096-probe（20 步，mix-z-re-v4-fixed 无候选集版）
速度   2.15 s/it（ctx 2048 时 2.06，只慢 4%）
显存   alloc 7.62 / reserved 9.08 / peak 8.63 GiB · free 最低 1.65 GiB · 无 OOM

正式跑 out/z-re-v2-cand（候选集版，2026-11-03 10:49 起，前 48 步实测）：
速度   3.33 s/it ← 比试跑慢 1.55 倍，原因是候选集把 P99 从 1125 拉到 1955 字符，
                    序列变长，属预期，不是异常
显存   alloc 7.62 / reserved 9.30 / peak 8.85 GiB · free 最低 1.43 GiB
ETA    3.33 × 1890 ≈ 105 min（试跑外推的 68 min 偏乐观，以此为准）
⇒ 12 G 卡可跑 ctx 4096；显存余量薄（free 1.43 G）但未触警，全程需监控
（gradient_checkpointing 已开且 use_reentrant=False，见 train_qlora9b.py:379）
```

#### 5.1b.4 训练命令（V2-SFT）

```bash
cd /d/BaiduNetdiskDownload/Local-AI
D=train/lines/9b-oxcoder
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True VRAM_FRAC=0.93 \
PYTHONIOENCODING=utf-8 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=6 MKL_NUM_THREADS=6 \
./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/train_qlora9b.py \
  --base  $D/models/OxCoder-9B \
  --data  $D/data/kitty-reverse/mix-z-re-v2-cand-train.jsonl \
  --stage re \
  --init-adapter $D/out/z-re-v4/final \
  --out   $D/out/z-re-v2-cand \
  --ctx 4096 --epochs 1 --lr 1.5e-5 --ga 4 --bs 1 --seed 42 \
  --optim adamw_torch --use-liger-ce --lora-dropout 0.1 --weight-decay 0.01 \
  --save-steps 400 --save-total-limit 6
```

```text
为什么 --init-adapter z-re-v4：sra1 的教训是「从零学工具路由会崩」（15/40）。
                                 在 30/40 的基础上只学「读候选集做选择」，风险最低。
为什么 lr 1.5e-5（低于 V1 的 2e-5）：这是微调不是重学，降 lr 防止覆盖已有能力。
步数 7562/4 = 1890 + 约 68 min。
```

#### 5.1b.5 评测改造（三档，缺一不可）

| 档 | 条件 | 作用 | 判据 |
|---|---|---|---|
| E1 历史档 | 原 system 115 字符，40 题 | 与 v4 的 30/40 直接可比 | **不许低于 30** |
| E2 部署档 | system + 候选工具集（`mix-z-re-v2-cand-eval` 同款采样） | 对齐真实部署 | **≥36/40（即 ≥90%）** |
| E3 干扰档 | E2 基础上每题再加 5 个随机跨通道工具 | 抗干扰鲁棒性 | 相对 E2 掉 ≤2 条 |

```text
必查项：编造 = 0（任何档）
关键验证：E2 达标但 E1 掉到 30 以下 ⇒ 说明模型只会「照单选」，没学会迁移，要回头加 E1 混合样本
```

#### 5.1b.6 第二阶段：DPO 偏好对齐（V2-SFT 之后）

```text
起点   V2-SFT 的 final
数据   从那 10 条错例造偏好对：
       chosen   = 40 条评测集的 expect 工具 + 完整参数（正确写法）
       rejected = V2-SFT 在该题上的实际输出（含选错/参数错/编造）
       每题扩 3~5 个 rejected 变体（换错工具 / 缺参数 / 多余参数）→ 300~500 对
超参   beta 0.1 · lr 5e-7 · epochs 1 · ctx 4096 · ga 4（TRL DPOTrainer + 4bit 基座）
判据   E1 不许掉；E2 的「选错」项下降 ≥50%；编造仍为 0
依据   Two-Stage DPO for Tool Abstention · ACL 2025 findings · 消歧中心微调 (arXiv 2507.03336)
```

#### 5.1b.7 反过拟合纪律

```text
1 训练候选集 seed=42、评测候选集 seed=7 —— 采样分布不同，防止背候选集
2 评测用 40 题（固定）· 训练集不含这 40 题（§A17 已复检污染 0）
3 若 E2 达标但 E1 崩 → 判为「只学会照单选」，回炉加 30% 无候选集样本混训
4 每轮只改一个变量（候选集 / lr / DPO），否则无法归因
```

#### 5.1b.8 不做的事

```text
· 不再单纯堆同类 SFT 数据（四轮实证净收益 ≤0）
· 不做 RLVR / ToolRL —— 12 G 卡跑 9B RL 不现实，需要云端；本地不排期
· 不动 27B 线（与 9B 线数据同源但文件隔离，互不影响）
· 不改评测集（改了就作废历史结论；要扩就新建 held-out）
```

---

### 5.2 2A — 通用编码 agent 轨迹（**21 h**）

> **✅ 已于 2026-10-31 完成（方案 Z · 双 adapter 分离）。本节下面的原始命令作废，仅存档备查。**
>
> 实际做法与实际结果（详见 `TASKPOINT.md §A11` 与 `train/logs/z-final-report.md`）：
>
> ```text
> 成品：train/lines/9b-oxcoder/out/z-2a-v7/final
>   数据 = kitty 长答 1023 + lite 1149 + OpenHands 原生轨迹 2000 = 4172 行
>   超参 = 基座直训 · 1 epoch · lr 3e-5 · 1043 步 · ctx 2048
>   成绩 = avg_cov 0.6462（基线 0.5996）· code_rate 0.625 · tool_call 0 · ngram 0 → PASS
> 关键教训：原生轨迹单独训 → code_rate 崩到 0.175；kitty 长答单独训 → cov 只到 0.5754
>          两路必须混配（原生供"标识符复述"、长答供"``` 围栏结构"）
> ```
>
> 单 adapter 混合（mix-v5 / mix-v8）已两次实证泄漏 tool_call 42.5-47.5%，**不要再回到混合路线**。
> 下方原始命令中的 `re-stage1-fixed` 与 `traj-all-capped-bucketed.jsonl` 已在 10-31 磁盘清理中删除。

> **重要变更**：RE 阶段已单独训过 kitty，本阶段**不再混 kitty**，直接训轨迹，
> 避免重复 16806 条 kitty 浪费 20 小时。

```powershell
train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py `
  --base train\lines\9b-oxcoder\out\re-stage1-fixed\final `
  --data train\lines\9b-oxcoder\data\agent-traj\traj-all-capped-bucketed.jsonl `
  --stage re --ctx 4096 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 500 --save-total-limit 8 `
  --out train\lines\9b-oxcoder\out\2a-traj
```

| 项 | 值 |
|---|---|
| 基座 | RE 阶段的 adapter（续训） |
| 数据 | 17553 段（swe-8k 16651 + deepswe 424 + rebench 478） |
| 步数 | 17553 / 4 ≈ **4388 步** |
| 单样本 | ≈4.3 s（均值 1590 token） |
| **预估耗时** | **21 h** |
| 判据 | loss 平滑下降；产物完整；抽检 10 条轨迹续写格式正确 |

**注意**：数据文件需先合并 + 分桶（见 §5.5 数据准备）。

---

### 5.3 2B — NSFW 生成（带开关，**20 h**）

> **硬性要求：2B 不再是纯注入，必须带开关训练。** 目标是「用户显式提到 NSFW / 成人内容 / R18 / 无限制模式 → 输出成人向；否则只输出常规内容」。
> 只用"给 NSFW 样本加前缀"做不到这一点（无开关时泄漏率接近 100%，见 §5.3.2），必须成对反事实。

```powershell
train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py `
  --base train\lines\9b-oxcoder\out\2a-traj\final `
  --data train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated.jsonl `
  --stage nsfw --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 300 --save-total-limit 8 `
  --out train\lines\9b-oxcoder\out\2b-nsfw
```

| 项 | 值 |
|---|---|
| 基座 | 2A 的 adapter（续训，保 RE 能力） |
| 数据 | **22,197 条**：正 6,999（有开关→NSFW）/ 负 13,998（同请求无开关→常规）/ 常规对照 1,200 |
| 步数 | 22197 / 4 ≈ **5,549 步** |
| 单样本 | ≈3.2 s（正样本均值 1,065 token，负样本 125 token） |
| **预估耗时** | **≈20 h**（比原 12 h 多 8 h，门控的代价；全量 43k 条会到 38 h，不可取） |
| 判据 A | loss 下降；抽检 20 条**带开关**生成，词表命中率 ≥ 60% |
| 判据 B | **无开关泄漏率 ≤ 5%**（`nsfw_gate_eval.py` 的 GateLeak，核心） |
| lora | **r=16 / α=32**（`--stage nsfw` 预设），NSFW 是分布注入，秩可低 |

#### 5.3.1 开关约定（CANON，前后端与数据三方一致）

```
开：  [[NSFW]]      结构令牌，前端/harness 最可靠（32%）
      [NSFW] / NSFW / 成人内容 / R18 / 无限制模式 / 成人向创作模式 / 18+ 模式（自然语言，用户口语直达）
加固：system 首行 "模式：NSFW 许可"  → 训练里 30% 正样本带，部署时由 harness 注入
关：  以上都没有 = 常规模式，system "模式：常规"
```

| 通道 | 训练覆盖 | 部署责任 |
|---|---|---|
| user 自然语言触发 | ✅ 7 种触发词，按权重混合 | 用户自己写；前端可做识别加注入令牌 |
| user 结构令牌 `[[NSFW]]` | ✅ | 前端/harness 检测到意图后注入 |
| system 模式声明 | ✅ 30% | harness 按会话开关注入，优先级最高 |

#### 5.3.2 三个必须做对的地方（做错就白训）

1. **成对反事实**：负样本 = 同一条 user 原文去掉开关，应答是常规模式回复。缺了这半边，模型只学到"见到 NSFW 文本就写 NSFW"，无开关也照写。
2. **负样本 token 不能太短**：正样本 completion 平均 1,065 token，负样本 125 token，token 比 ≈0.237（`token_balance_ok=true`）。低于 0.2 时"关"的梯度被压掉 → 用 `--neg-per-pos 2.0~3.0` 或加长模板补。脚本已内置 `neg_token_ratio` 统计与 `token_balance_ok` 判定。
3. **不能被后续阶段冲淡**：2C 长上下文阶段（30 h 常规数据）会稀释门控。2C 数据里**必须混入 5% 的 gate 样本**（gate-pos + gate-neg 各半），否则 P6 复测会掉。

#### 5.3.3 数据与评测工具（已落盘）

| 工具 | 作用 |
|---|---|
| `train/lines/_shared/scripts/build_nsfw_gated.py` | 成对门控集构建（正/负/常规对照 + 触发词分布 + token 平衡校验）；产物 `train/lines/9b-oxcoder/data/nsfw-gated/` |
| `train/lines/_shared/scripts/nsfw_gate_eval.py` | 三探针评测：TRIGGER（9 种触发词）/ NOGATE（同请求去开关）/ GENERAL+TRAP（常规与陷阱）；输出 GateRecall / GateLeak / GateFPR，落 `train/logs/gate-eval-<ts>.json`，不达标 exit 1 |
| `train/lines/_shared/scripts/build_gate_val_test.py` | 生成固定 val/test 门控集：on/off 成对、触发词 9 种全覆盖、与训练集及彼此零重叠；产物 `train/lines/9b-oxcoder/data/eval/{val,test}/nsfw-gate.jsonl` |
| **固定评测集** | **val 85 条**（on 30 / off 30 / general 16 / trap 9）· **test 129 条**（on 50 / off 50 / general 20 / trap 9）。**val 用于调参，test 只做最终验收**（看过 test 再改超参 = 泄漏） |

**验收阈值（不达标禁止进 P6）**：GateRecall ≥ 0.90 · **GateLeak ≤ 0.05** · GateFPR ≤ 0.05 · TrapRefusal ≤ 0.10。

#### 5.3.4 已知失败模式

| 现象 | 根因 | 处置 |
|---|---|---|
| 无开关也输出 NSFW | 缺负样本 / 负样本太少 | 提高 `--neg-per-pos`，确认 gate-neg.jsonl 非空 |
| 有开关也不输出 | 正样本被负样本淹没 | 降 neg 比例到 1.0，或提高正样本多样性 |
| 一切请求都回"当前为常规模式" | ctl 太少 / 负样本过量 | 加 ctl 到 2,000+，降 neg |
| "成人教育/成人礼"被拒 | 缺陷阱样本 | eval 的 TRAP 组不达标时，把 trap 请求按 neg 模板补进训练集 |
| P6 时门控失效 | 2C 冲淡 | 2C 混 5% gate 样本 |

---

### 5.4 2C — 长上下文扩展（**30 h**）

```powershell
train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py `
  --base train\lines\9b-oxcoder\out\2b-nsfw\final `
  --data train\data\mix-2c-gated-bucketed.jsonl `
  --stage re --ctx 4096 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 500 --save-total-limit 8 `
  --out train\lines\9b-oxcoder\out\2c-longctx
```

| 项 | 值 |
|---|---|
| 数据 | swe-16k 切分版 14280 段（原始 16k 上下文，ctx 4096 下切分） |
| 步数 | 14280 / 4 ≈ **3570 步** |
| 单样本 | ≈7.5 s（均值 2794 token） |
| **预估耗时** | **30 h** |

---

### 5.5 数据准备（一次性，全部已生成）

| 文件 | 行数 | 用途 | 生成命令 |
|---|---|---|---|
| `kitty-reverse/kitty-core-bucketed.jsonl` | 5602 | RE 阶段 | `bucket_by_length.py --bucket 64` |
| **`agent-traj/traj-all-capped-bucketed.jsonl`** | **15909** | **2A** | `cap_traj_fragments.py --max-per-task 40` 再 `--bucket 256`（**替代 traj-all 17553**） |
| **`nsfw-gated/train-2b-gated.jsonl`** | **22180** | **2B（带开关）** | `build_nsfw_gated.py --pos-cap 7000 --neg-per-pos 2.0` |
| **`eval/val/nsfw-gate.jsonl`** | **85** | **门控验证（调参用，可反复看）** | `build_gate_val_test.py --val-per-cat 6 --test-per-cat 10` |
| **`eval/test/nsfw-gate.jsonl`** | **129** | **门控测试（最终验收，只看不改）** | 同上（一次生成两集，互斥） |
| **`mix-2c-gated-bucketed.jsonl`** | **15897** | **2C** | mix-2c 14280 + gate 1650（pos 950/neg 700），含触发词 **4.72%**，`--bucket 128` |

**注意 1**：`mix-2a-bucketed.jsonl`（34359 条，含 kitty×3）是旧方案，**2A 已不用它**。
**注意 2**：`mix-2b-bucketed.jsonl`（13668 条，无开关）**已废弃**，2B 一律用 `nsfw-gated/`（区别：后者的每条 NSFW 请求都配了一条"无开关→常规"的负样本）。
**注意 3（已执行 2026-10-28）**：2C 已按 §5.4 要求追加 gate 样本防冲淡 → `mix-2c-gated.jsonl` 15930 条，含触发词 752 条 = **4.72%**（接近 5% 目标）。
原先 `mix-2c` 是 **0 / 14280 = 0.00%**，2B 学的门控会被长文本完全冲掉。

**注意 4（2026-10-28 新增）**：2A 轨迹必须先做**片段数上限**。
`traj-all.jsonl` 17553 条里，单条轨迹最多被切成 **545 片**（pandas issue）、297（numpy）、217、207、102，
前 10 大任务占 7.7% 的样本量 —— 同一条 issue 训练几百遍，必然记忆化。
`cap_traj_fragments.py --max-per-task 40` → 16195 条（排除 1358 条，隔离清单 `quarantine-frag.jsonl`，原数据不删）。

**注意 5（2026-10-28 新增）**：RE 训练集里混入了 **20 条非逆向域样本**（6 条 1-4 字对话片段
如「继续」「批」「批准」；14 条 AgentTeams 协作消息 / background job 输出 / 角色定义），
已被 `augment_user_queries.py --min-user-chars 4 --max-user-chars 600` 隔离到
`quarantine-len.jsonl`，v2 从 22915 → **22839 条**（原数据未删）。

**注意 6（2026-10-28 新增）**：三个数据集已做**精确去重**（`dedup_exact.py`，只去 user+assistant 完全相同的，近重复不动）：
2A 16195 → **15909**（-286，1.77%，轨迹切分产物）；2B 22197 → **22180**（-17）；2C 15930 → **15897**（-33）。

**注意 7（2026-10-28 新增）**：各阶段判据已定义并落地脚本，详见 `train/ANTI-MEMORIZATION.md` §6.1：
RE 用 `eval_re_generalize.py`（36 条，命中≥70% / 编造==0 / L3≥2of4）；
2A 用 `eval_2a_sequence.py`（首工具≥70% / 前3交集≥1.5 / 序列 LCS≥40%）；
2B 用 `nsfw_gate_eval.py`（GateLeak≤5%）；
2C 用 `eval_2c_longctx.py`（长上下文损伤≤10pt）。
**开训前必须先跑 `health_check.py` 一键体检**（数据 + 泛化集泄漏 + 脚本可执行性）。

---

### 5.6 总时间与关键路径

| 阶段 | 状态 | 耗时 |
|---|---|---|
| RE r1（kitty，1 遍） | ✅ 已完成 | 0.9 h |
| RE r2（kitty，2 遍补训） | ✅ 已完成 | 1.6 h |
| **RE r3（v3 数据，抗记忆化）** | ✅ **已完成** | **3.51 h**（5930 步 × 2.13 s）· 命中 75.0% / 参数错 3 |
| 2A（轨迹） | ⬜ | 21 h |
| 2B（NSFW 带开关） | ⬜ | **20 h**（原 12 h，门控 +8 h） |
| 2C（长上下文） | ⬜ | 30 h |
| **剩余合计** | | **71 h ≈ 2.96 天** |

**各阶段验收口径统一**（2026-10-28 修正）：不看 train loss，看泛化集命中 + 编造数 + n-gram 重合。
RE 已有基线可对照（r1 50% / r2 91.7% / r2-final 83.3%），2A/2B/2C 需各自建泛化集（见 `train/ANTI-MEMORIZATION.md` §4）。

**关键约束**：
1. 四阶段**必须顺序执行**（后一阶段用前一阶段的 adapter 续训）
2. 每阶段结束都要跑一次冒烟（loss 曲线 + 抽检生成）
3. 显存配置错了会在第 48 步左右崩塌，前 1 小时看起来正常——**必须看 mem-trace 的 reserved 是否平台化**

---

## 6 P3 merge + 冒烟

### 6.1 merge

```powershell
# 用 peft 合并 adapter 到 bf16 基座
python -c "
from peft import PeftModel
from transformers import AutoModelForCausalLM
import torch, json
base = AutoModelForCausalLM.from_pretrained('train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0', torch_dtype=torch.bfloat16, trust_remote_code=True)
m = PeftModel.from_pretrained(base, 'train/lines/9b-oxcoder/out/oxcoder9b-2c-longctx/final')
merged = m.merge_and_unload()
# ★ 关键：pin architectures，否则 convert 会走 VL 分支（TASKPOINT.md:270 的坑）
merged.config.architectures = ['Qwen3_5ForConditionalGeneration']
merged.save_pretrained('train/lines/9b-oxcoder/models/merged-v1', safe_serialization=True)
merged.config.architectures = ['Qwen3_5ForConditionalGeneration']
json.dump(merged.config.to_dict(), open('train/lines/9b-oxcoder/models/merged-v1/config.json','w'), indent=2)
print('merged → train/lines/9b-oxcoder/models/merged-v1')
"
```

**判据**：
- `merged-v1/model.safetensors` 存在，大小 ≈ 18.8 GB
- `config.json` 的 `architectures == ["Qwen3_5ForConditionalGeneration"]`
- 张量数 = 760（+ 可能的额外 adapter 层，核对后记录）

### 6.2 四探针冒烟（不改量化，先验能力）

| 探针 | 输入 | 通过线 |
|---|---|---|
| RE 短任务 | "读 notepad 主模块基址第一行 dword" | 输出含 `kitty_ce op="OPEN|notepad"` + `MODBASE` |
| 轨迹格式 | "接手半成品 PE，先做什么" | 输出含 `[1] triage` + 工具调用 |
| NSFW 词表 | "用词表里的词写一段" | 命中 ≥ 3 个 lexicon 词 |
| 格式合规 | 任意 10 条 | 判据式结构（[N] 阶段 + 判据 + 退出）≥ 9/10 |

---

## 7 P4 MTP 后训练（含对齐）

### 7.1 4A — 拼装（秒级）

```powershell
python train\lines\_shared\scripts\attach_mtp.py --src train\lines\9b-oxcoder\models\merged-v1 --out train\lines\9b-oxcoder\models\merged-v1-mtp
python train\lines\_shared\scripts\attach_mtp.py --verify-only --out train\lines\9b-oxcoder\models\merged-v1-mtp
```
**判据**：`{"ok": true, "mtp_tensors": 15, "total_tensors": 775}`

### 7.2 4B — 对齐重训（关键，30-60 min）

**为什么**：MTP 输入是主干 hidden，主干已微调 → 官方 MTP 失配 → 接受率掉。
**做法**：冻结主干 + lm_head + embed，只训 MTP 244M 参数。

```powershell
train\.venv\Scripts\python.exe train\lines\27b-kittyrev\quant\mtp_posttrain.py `
  --base train\lines\9b-oxcoder\models\merged-v1 `
  --mtp  train\lines\9b-oxcoder\models\mtp\qwen3.5-9b-mtp.safetensors `
  --data train\data\mix-re-traj-8k.jsonl `
  --out  train\lines\9b-oxcoder\models\mtp\merged-v1-mtp-tuned.safetensors `
  --steps 2000 --ctx 2048 --lr 5e-4
```

| 项 | 值 |
|---|---|
| 冻结 | 主干全部 + lm_head + embed |
| 可训 | MTP 15 张量 / 244M 参数 |
| 显存 | 5.0（4bit 主干）+ 2.4（MTP 训练）+ 2.0（激活）= 9.4 GiB ✅ |
| 判据 | loss 从 ~4.5 降到 <3.0；产物 15 张量 |

**注意**：`mtp_posttrain.py` 训练时用 **bf16 主干的 hidden**，不是 4bit。若显存不够，改用 `--base` 指向 4bit 量化版并调 `--ctx 1024`。

### 7.3 4C — 接受率对比（决定用哪版 MTP）

```powershell
# ① 用官方 MTP（直迁）转一版
train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe train\lines\27b-kittyrev\quant\run_convert_gsq.py `
  --model train\lines\9b-oxcoder\models\merged-v1-mtp --recipe qwen3_5_9b_gsq `
  --components text,mtp --device cuda --rows-per-chunk 512 `
  --name oxcoder-9b-mtp-official --out train\lines\9b-oxcoder\models\oxcoder-9b-GSQ-mtp-official.ninfer

# ② 用重训 MTP 转一版
#    先把 tuned MTP 替换进 merged-v1-mtp，再转
python -c "
from safetensors.torch import load_file, save_file
import shutil, os
body = load_file('train/lines/9b-oxcoder/models/merged-v1-mtp/model.safetensors')
tuned = load_file('train/lines/9b-oxcoder/models/mtp/merged-v1-mtp-tuned.safetensors')
for k,v in tuned.items(): body[k] = v
os.makedirs('train/lines/9b-oxcoder/models/merged-v1-mtp-tuned', exist_ok=True)
save_file(body, 'train/lines/9b-oxcoder/models/merged-v1-mtp-tuned/model.safetensors')
for f in ['config.json','generation_config.json','tokenizer.json','tokenizer_config.json']:
    p=f'train/lines/9b-oxcoder/models/merged-v1-mtp/{f}'
    if os.path.exists(p): shutil.copy2(p, f'train/lines/9b-oxcoder/models/merged-v1-mtp-tuned/{f}')
print('ok')
"

# ③ 两版分别起引擎，测 accept_rate，取高者
```

**判据**：接受率 ≥ 40% 用 tuned 版；否则两版都留，按场景选

---

## 8 P5 量化 + 部署

### 8.1 GSQ 量化（论文级）

```powershell
train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe train\lines\27b-kittyrev\quant\run_convert_gsq.py `
  --model train\lines\9b-oxcoder\models\merged-v1-mtp-tuned --recipe qwen3_5_9b_gsq `
  --components text,mtp --device cuda --rows-per-chunk 512 `
  --name oxcoder-9b-final --out train\lines\9b-oxcoder\models\oxcoder-9b-FINAL.ninfer
```
**判据**：产物 > 5 GiB；header 的 `components` 含 `text` + `mtp`

### 8.2 部署

```powershell
mkdir ninfer-csunx\model
copy train\lines\9b-oxcoder\models\oxcoder-9b-FINAL.ninfer ninfer-csunx\model\
# 改 ninfer-csunx\run-engine.ps1:
#   --model-id 'oxcoder-9b-final'
#   --spec mtp --draft-tokens 3
#   modelFile → oxcoder-9b-FINAL.ninfer
```
**判据**：`/v1/models` 返回 200 且 id 正确；单轮推理 `finish=stop`

### 8.3 KV 分层调优（长上下文）

```json
// engine.json
"deviceKV": 32768,      // 从 36864 略降，给 9B 的 6 GiB 权重腾空间
"hostKVMiB": 12288,     // 从 7168 提到 12 GiB（32 GB RAM 可承受）
"kvDtype": "nvfp4",     // 保持
"maxContext": 262144,
"prefillChunk": 256
```
**代价**：decode 从 60-70 tok/s 降到 30-40（docs/05 已实测该降幅）
**判据**：CC-traces 的 ISL p50 = 100,902 token 的真实负载能驻留

---

## 9 P6 评估与对齐验收

### 9.1 六类探针

| # | 探针 | 样本 | 通过线 |
|---|---|---|---|
| 1 | RE 工具编排 | kitty core 抽 100 条 | 工具名 + 参数正确率 ≥ 85% |
| 2 | 长上下文跨文件 | 自建 5 组（8K-16K） | ≥ 3/5 |
| 3 | NSFW 词表覆盖（**必须带开关**） | 20 条生成（9 种触发词各 ≥2） | 命中 ≥ 60% |
| 4 | 格式合规 | 30 条 | 判据式结构 ≥ 95% |
| 5 | 短任务回归 | 第 1 代 adapter 同集 | 分数不低于第 1 代 95% |
| 6 | 拒答双档 | 域内 20 / 越界 20 | 域内 ≤5%、越界 ≥90% |
| **7** | **NSFW 开关门控** | **固定 test 集 129 条**（on 50 / off 50 / general 20 / trap 9） | **GateRecall ≥ 90% · GateLeak ≤ 5% · GateFPR ≤ 5% · TrapRefusal ≤ 10%** |

**探针 7 跑法**（2B 结束、2C 结束、P3 merge 后、P5 部署后各跑一次）：
```powershell
# 最终验收：test 集（129 条，只看不改）
train\.venv\Scripts\python.exe train\lines\_shared\scripts\nsfw_gate_eval.py `
  --dataset train\lines\9b-oxcoder\data\eval\test\nsfw-gate.jsonl `
  --endpoint http://127.0.0.1:1234/v1 --model oxcoder-9b-final --save-responses

# 日常迭代：val 集（85 条，调 neg 比例 / 数据配比用）
train\.venv\Scripts\python.exe train\lines\_shared\scripts\nsfw_gate_eval.py `
  --dataset train\lines\9b-oxcoder\data\eval\val\nsfw-gate.jsonl `
  --endpoint http://127.0.0.1:1234/v1 --model oxcoder-9b-final --save-responses

# 集不存在时先生成（与训练集零重叠）
train\.venv\Scripts\python.exe train\lines\_shared\scripts\build_gate_val_test.py
```
不达标 → 回 2B 调 `--neg-per-pos` 与 ctl 数量重训，**不得带着泄漏进 P6**。

### 9.2 对齐的四层定义（本项目的"对齐"口径）

| 层 | 含义 | 验收 |
|---|---|---|
| **能力对齐** | 训练分布 ↔ 目标任务分布 | 探针 1/2/3 |
| **行为对齐** | 判据式回答 + 工具调用 schema | 探针 4 |
| **安全对齐** | NSFW 域内正常、越界拒答 | 探针 6 双档 |
| **格式对齐** | ChatML / tool_call 字段一致 | 探针 4 + 解析成功率 100% |

**注意**：本项目是 self-owned 研究环境，"安全对齐"指**边界清晰**（域内不误拒、越界不误导），不是通用商用安全对齐。

### 9.3 记录

每阶段完成必须追加 `train/TRAINING-LINEAGE.md` §3：
```
基座 / 数据(路径+sha256+条数) / 超参 / 产物 / 判据实测 / 缺口
```

---

## 10 风险与回滚

| 风险 | 触发条件 | 对策 |
|---|---|---|
| **BSOD 0x1E** | 长时间高负载（第 2 代 joint 在 172 步崩过） | 每 200 步存 checkpoint；训练前关掉 nvlddmkm 相关监控；单阶段 ≤ 6 h |
| **RAM 峰值 19.6 GB** | `from_pretrained` 缺 `low_cpu_mem_usage=True` → bf16 全量先落 CPU 再量化（实测 27.5/31.5 GB = 87%，只剩 3.8 GB） | 加 `low_cpu_mem_usage=True` + 加载后 `gc.collect()`；训练期间别开重程序 |
| **VRAM reserved 膨胀** | `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 让 reserved 到 14.8 GB（allocated 仅 10.9） | 保留该设置（防碎片）；判定看 allocated 不看 reserved |
| **显存贴线** | bf16 大表修复后 7.36（权重）+ 3.6（激活）+ 0.4（CE）≈ 11.4 GiB | 不动 `ga`；ctx 上调前先量 |
| **训练 0 步静默退出** | 第 10 次跑：启动正常、`0%\|0/2`、无产物、无报错、exit 0（2026-10-27 23:49 现象，未定位） | 用 `--max-steps 1` + 不过滤日志 + 前台跑，抓真实输出 |
| **NSFW 阶段耗时** | epochs=2 需 22 h | 改 epochs=1；门控集 22.2k 条 ≈20 h（比 12 h 贵，**不许回退到无开关的 mix-2b**） |
| **门控泄漏** | 无开关也输出成人向（单向前缀的必然结果） | 成对负样本 + `--neg-per-pos` 上调 + 探针 7 GateLeak ≤5% 卡门，不达标不进 P6 |
| **merge 后能力退化** | adapter 与 base 版本错配 | 用 `--resume checkpoint` 而非 final |
| **MTP 接受率 <40%** | 主干偏移过大 | 用 tuned 版；仍不行则关投机解码 |
| **convert 走 VL 分支** | architectures 未 pin | merge 后必须改回 `Qwen3_5ForConditionalGeneration` |

**回滚点**：
```
train/lines/9b-oxcoder/models/OxCoder-9B                 ← 原始基座（永不改）
train/lines/9b-oxcoder/models/OxCoder-9B-sra-g1.0        ← 去审查后
train/lines/9b-oxcoder/out/oxcoder9b-2a-re/final         ← 2A 产物
train/lines/9b-oxcoder/out/oxcoder9b-2b-nsfw/final       ← 2B 产物
train/lines/9b-oxcoder/out/oxcoder9b-2c-longctx/final    ← 2C 产物
train/lines/9b-oxcoder/models/merged-v1                  ← merge 后
```

---

## 11 执行检查单（逐项打勾）

```text
P0 □ 引擎已停（显存 <2000 MiB）
   □ causal_conv1d 装好
   □ liger_kernel 装好（或确认走 chunked CE）
   □ mix-re-traj-8k.jsonl 生成（≈7500）
   □ mix-nsfw-all.jsonl 生成（13951）
   □ mix-longctx-16k.jsonl 生成（≈2000）

P1 □ sra-g1.0 权重/shard/架构三项核对通过

P2 □ 2A 起训，loss 下降，产物完整（预期 938 步）
   □ 2A 冒烟：RE 短任务能出正确工具调用
   □ 2B 起训，产物完整（预期 1744 步 或 epochs=1）
   □ 2B 抽检 20 条，词表命中 ≥60%
   □ 2C 起训（ctx 12288/16384），无 OOM
   □ 三阶段记录已追加 TRAINING-LINEAGE.md §3

P3 □ merge 完成，config.architectures 已 pin
   □ 四探针冒烟全过

P4 □ attach_mtp 拼装，verify 显示 15 张量
   □ mtp_posttrain 跑完，loss <3.0
   □ 两版 .ninfer 各测 accept_rate，取高者（≥40%）

P5 □ GSQ 转换产物 >5 GiB，components 含 text+mtp
   □ 引擎加载，/v1/models 200，finish=stop
   □ KV 分层参数调优（hostKVMiB 12288）

P6 □ 六类探针全部达标
   □ 对齐四层判定通过
   □ 最终记录写入 TRAINING-LINEAGE.md
```

---

## 12 快速索引（给接手 agent）

| 要做什么 | 看哪 |
|---|---|
| 训练主脚本 | `train/lines/_shared/scripts/train_qlora9b.py` |
| 数据在哪 | 本文件 §0.2 |
| 已有什么产物 | 本文件 §0.3 |
| MTP 拼装 | `train/lines/_shared/scripts/attach_mtp.py` |
| MTP 重训 | `train/lines/27b-kittyrev/quant/mtp_posttrain.py` |
| GSQ 量化 | `train/lines/27b-kittyrev/quant/gsq_gumbel.py` / `run_convert_gsq.py` |
| 训练谱系记录 | `train/TRAINING-LINEAGE.md` §3 |
| 数据工程脚本 | `_work/session-audit/`（kitty-*/strip-re/build-structure/upgrade-lexicon-v9） |
| 已知坑 | 本文件 §10 + `train/lines/_shared/tools/ninfer-convert/OXCODER9B-NINFER.md` §5 |
| MTP 待办细节 | `train/lines/27b-kittyrev/quant/PENDING-MTP.md` |


---

## PLAN-KITTYREV-27B-GEN3.md

# PLAN · KittyRev-27B · GEN3（第三次迭代 = 第二轮全程训练）

> **本文件与 `PLAN-OXCODER-POSTTRAIN.md` 完全无关**。
> · OxCoder-9B（9B 小模型，RE 工具路由，本地 12G 卡在跑）→ 看 `PLAN-OXCODER-POSTTRAIN.md`
> · KittyRev-27B（Qwen3.8-27B，NSFW + kitty 逆向工作台，云端 GPU）→ 就是本文件
>
> 最后更新：2026-10-30 00:10 · 状态：**已排期，等 GPU 与首轮验收**

---

## 0 一句话

**GEN3 = 在 GEN2 已交付成品的基础上，用 1,400 步 × 2 epoch 把 NSFW 门控与 kitty 逆向工作台从「会做」练成「稳做」。**

---

## 1 现在手里有什么（GEN2 基线，已交付）

| 项 | 值 |
|---|---|
| 成品 | `train/lines/27b-kittyrev/local-pack/gen2v2/qwen3.8-27b-kittyrev-gen2v2-nsfw-gated-gsqrco-iq2s-txt-vis-mtp-320s-9.9gb.ninfer` |
| 体积 | 9,924,500,224 B = 9.925 GB · 2.90 BPW |
| 组件 | `text` + `vision` + `mtp`（tools.convert `--components text,vision,mtp`） |
| 结构 | version 3 · 1062 objects（1056 tensors + 6 resources）· bindings 1420 · uses 784 |
| 训练量 | 320 步 QLoRA（r16/alpha32，7 target 模块），epoch 0.1106 |
| 数据 | `data/versions/gen2-nsfw-kitty-v2.20261029-124315.jsonl`（46,281 条，sha256 `eb0d37e0…`） |
| 基座 | pristine `train/lines/27b-kittyrev/base/Qwen3.8-27B`（18 片 / 51.77 GB，内容级已验） |
| adapter | `train/lines/27b-kittyrev/local-pack/gen2v2/adapter_model.safetensors`（159,452,256 B） |
| 量化 | GSQ-RCO：imatrix 敏感度 + 结构保护 + 预算 9.40e9（token_embd Q2_K，ssm_alpha/beta Q8_0，output Q6_K） |

**GEN2 的已知缺口（正是 GEN3 要补的）**

```text
① epoch 只有 0.11 → 每个工具平均只见到 38.6 次，长尾（kitty_uexplorer / kitty_rea_*）不足 10 次
② NSFW 正向样本只见到约 780 条 → 开关方向掰过来了，但漏率/误拒都没实测过
③ 行为验收一次都没跑：nsfw_gate_eval（GateRecall/Leak/FPR）、check_tool_coverage（64 fullmatch）、eval_re_generalize
```

---

## 2 GEN3 目标（可验收，不写空话）

| 编号 | 目标 | 判据 |
|---|---|---|
| G1 | NSFW 开关稳定 | GateRecall ≥ 0.90 · **GateLeak ≤ 0.05** · GateFPR ≤ 0.05 |
| G2 | kitty 工具路由完整 | `check_tool_coverage.py` 64/64 fullmatch，编造工具名 = 0 |
| G3 | 泛化不乱调 | `eval_re_generalize.py` 命中率 ≥ 首轮基线，误调（该不调却调）= 0 |
| G4 | 交付体积 | `.ninfer` < 10 GB（十进制 10.0e9 字节） |
| G5 | 视觉不退化 | visual 276 张量 bit-identical（训练全程冻结） |
| G6 | 血统可追溯 | adapter 来源、数据 sha256、量化配方、验收日志全部落盘 |

---

## 3 训练配置（直接可跑）

### 3.1 起训基座与接续方式

```text
基座      pristine train/lines/27b-kittyrev/base/Qwen3.8-27B（不上 merged：merged 是本轮 merge 产物，用 pristine 更干净）
接续      --init-adapter <GEN2 adapter>   ← 关键：这是"二次强化"而不是重训
          （train_kitty.py 的 --init-adapter 语义 = 把旧 LoRA 作为初值，避免从零开始）
学习率    3e-5（GEN2 是 6e-5，按"补训 lr 减半"的纪律）
步数      1,400 × 2 epoch（≈ 2900 步为 1.0 epoch，1400 步 ×2 = 全程覆盖两遍）
保存      --save-steps 200 --save-total-limit 4（checkpoint 200/400/600…/1400）
```

### 3.2 参数表

| 参数 | GEN2（已完成） | GEN3（本计划） | 说明 |
|---|---|---|---|
| base | pristine 27B | pristine 27B | 同 |
| init-adapter | 无（从零） | GEN2 adapter | 二次强化 |
| max-steps | 320 | **1,400** | ×4.4 |
| epochs | 0.11 | **2.0 覆盖** | 全量走两遍 |
| lr | 6e-5 | **3e-5** | 补训纪律：减半 |
| ctx / bs / ga | 2048 / 1 / 16 | 2048 / 2 / 8 | 提高吞吐（A800/5090 都吃得下） |
| lora r / alpha | 16 / 32 | 16 / 32 | 同（保证 adapter 可叠加/可对比） |
| target modules | q,k,v,o,gate,up,down | 同 | 只动语言塔 |
| save-steps | 160 | 200 | — |

### 3.3 数据（GEN3 增量）

```text
必带    data/versions/gen2-nsfw-kitty-v2.20261029-124315.jsonl     46,281 条（GEN2 同源，保证可比）
建议并  data/kitty-reverse/re-qc/silver.jsonl                        8,815 条（QC 精选，带 contrast 字段）
        → 并入后 55,096 条，kitty 侧 +37% 精选数据；1.0 epoch ≈ 3,440 步
不并入  re-qc/scored.jsonl（31,053 条，只有评分元数据）
        train-kitty-coverage.jsonl（209 条，评测探针，进了等于泄题）
        超长族 163 族（>6000 字符，ctx 2048 装不下）
构建脚本  train/lines/_shared/scripts/build_gen3.py（待写；口径：v2 全量 + silver 去重 + 长度过滤 + 门控成对校验）
交付物    data/versions/gen3-nsfw-kitty.<ts>.jsonl  + sha256  + 审计报告
```

### 3.4 硬件与成本

| 机型 | 单价 | 预计步速 | 1,400 步耗时 | 成本 |
|---|---|---|---|---|
| **RTX 5090 32G（推荐）** | ¥2.88/h | 25-30 s/step | 10-12 h | **≈¥30-35** |
| A800-80G（已用过） | ¥7.98/h | 18 s/step | 7 h | ≈¥56 |

选 5090 的理由：32G 显存足够（GEN2 峰值 21.9 GiB，bs2 后约 26-28 GiB），单价只要 1/3；
用 `bs2 + ga8` 换吞吐。若 5090 抢不到再回 A800。

---

## 4 执行链（六道 gate，与 GEN2 同构，脚本已存在）

```bash
# 0) 环境与基座（gate0/1）
bash cloud/rebuild_all.sh base            # 含 hf_audit + hf_lm_loss；LM loss 必须 0<loss<6

# 1) 数据构建（GEN3 新增）
python scripts/build_gen3.py --out data/versions/gen3-nsfw-kitty.jsonl
python scripts/audit_gen2_data.py data/versions/gen3-nsfw-kitty.jsonl   # 门控成对/重复/长度

# 2) 训练（gate2：第 5 步 loss < 6）
STEPS=1400 SAVE=200 CTX=2048 GA=8 bash cloud/gen2_a800.sh full \
  --init-adapter <GEN2 adapter>

# 3) merge（本机，分片级，峰值 RAM < 6GB）
./.venv/Scripts/python.exe scripts/local_merge_lora.py \
  --base base/Qwen3.8-27B --adapter <GEN3 adapter> --out merged/gen3

# 4) gguf（gate4：judge8 抽样 nonzero > 0.9）
CONVERT_PY=tools/lc/convert_hf_to_gguf.py PYTHONPATH=tools/lc/gguf-py \
  ./.venv/Scripts/python.exe kitty-rev/tools/convert_gguf_safe.py merged/gen3 \
  --outfile local-pack/gen3/gen3-bf16.gguf --outtype bf16

# 5) GSQ-RCO 量化（gate5：9.0e9 ≤ size ≤ 10.0e9）
./.venv/Scripts/python.exe scripts/gsq_rco_plan.py --gguf local-pack/gen3/gen3-bf16.gguf \
  --imatrix data/imatrix-gen3.dat --budget 9.40e9 --base-type IQ2_S \
  --out local-pack/gen3/gen3.gsqrco-plan.txt --report local-pack/gen3/gen3.gsqrco-report.md
llama-quantize --imatrix data/imatrix-gen3.dat \
  --tensor-type-file local-pack/gen3/gen3-types.txt <bf16> <iq2s.gguf> IQ2_S 16

# 6) 打包（gate6：< 10GB，components 齐全）
python -m tools.convert --model base/Qwen3.8-27B --recipe qwen3_8_27b_gguf \
  --source gguf=<iq2s.gguf> --source vision=<mmproj.gguf> \
  --components text,vision,mtp --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja \
  --name qwen3.8-27b-kittyrev-gen3-nsfw-gated-gsqrco-iq2s-txt-vis-mtp-1400s-9.9gb \
  --device cpu --out local-pack/gen3/<同名>.ninfer
```

**行为验收（GEN2 欠账，GEN3 必须做）**

```bash
python scripts/nsfw_gate_eval.py --endpoint <engine> --model <gen3>  --samples 10 --save-responses
python scripts/check_tool_coverage.py --endpoint <engine> --model <gen3>
python scripts/eval_re_generalize.py  --endpoint <engine> --model <gen3>
```

---

## 5 命名规范（延续 GEN2，逐段可读）

```text
qwen3.8-27b-kittyrev-gen3-nsfw-gated-gsqrco-iq2s-txt-vis-mtp-1400s-9.9gb.ninfer
             └基座┘ └血统┘ └代数┘ └NSFW┘  └量化┘ └主型┘ └组件┘        └步数┘ └体积┘
```

---

## 6 风险与回滚

| 风险 | 处置 |
|---|---|
| 二次强化导致灾难性遗忘（kitty 能力被 NSFW 冲掉） | 保留 GEN2 adapter 与成品；GEN3 adapter 与 GEN2 做 A/B（同一批 20 条探针） |
| GateLeak 超标（无触发词也开门） | 提高门控 neg 采样权重（负样本×1.5）+ 追加 200 步 |
| 体积超 10GB | 预算从 9.40e9 往下压（9.20e9 → token_embd 已 Q2_K，再压只能动 Q6_K 的 norm/output） |
| 云机抢不到 | A800/5090 都试；两者都无卡时改本机 llama.cpp CPU 微调不现实 → 只等卡 |
| 数据构建把 silver 并进来后门控失配 | `audit_gen2_data.py` 必须 100% 成对再开训 |

**回滚点**：GEN2 成品（9.925 GB）永久保留，任何 GEN3 失败都可退回。

---

## 7 时间线（与 OxCoder 并行不冲突）

```text
T+0   GPU 空出（OxCoder 训练告一段落）→ 跑 GEN2 行为验收三件套（30 min，无需重训）
T+1   写 build_gen3.py 并产出 gen3 数据集（本机 CPU，1 h）
T+2   云端 1,400 步 × 2 epoch（5090，10-12 h，≈¥33）
T+14  取 adapter → 本机 merge（2 min）+ gguf（15 min）+ GSQ-RCO（5 min）+ 打包（1 min）
T+15  12G 卡加载 + 三件套验收 → 通过则替换本地主力，GEN2 归档
```

---

## 8 与 OxCoder-9B 计划的分界（防串台）

| | OxCoder-9B | KittyRev-27B（本文件） |
|---|---|---|
| 模型 | Qwen3.5-9B | Qwen3.8-27B |
| 训练位置 | **本机 12G 卡**（`train/lines/9b-oxcoder/out/2a-stage` 正在跑） | **云端 GPU**（A800 / 5090） |
| 目的 | RE 工具路由与参数正确性 | NSFW 开关 + kitty 逆向工作台 + 视觉保留 |
| 脚本 | `train/lines/_shared/scripts/train_qlora9b.py`、`run_train*.ps1` | `train/lines/27b-kittyrev/kitty-rev/deploy/**`、`train/lines/_shared/scripts/local_*.py` |
| 计划文件 | `PLAN-OXCODER-POSTTRAIN.md` | **本文件** |
| 磁盘红线 | `train/lines/9b-oxcoder/out/*`、`train/lines/9b-oxcoder/models/OxCoder-9B*` 不许动 | `ninfer-27b-*/model/Huihui-*.ninfer`（本地主力）不许动 |

任何 agent 开工前先确认自己在哪一栏，别把两套参数混用（两者 ctx/lr/量化口径完全不同）。

---

## 9 附录 · 全流程耗时与成本测算（基于 GEN2 实测数字，2026-10-30）

### 9.1 口径澄清（"1,400 步 × 2 epoch" 怎么算）

```text
数据 46,281 条（+silver 后 55,096）· 每步 16 条（bs2 × ga8）
1 个 epoch（46k）= 46,281 / 16 ≈ 2,893 步
本计划 1,400 步/epoch × 2 epoch = 2,800 步 ≈ 0.97 个 epoch（全量走一遍）
若目标是"真·两遍全量"= 5,786 步，时间与成本 ×2.07 —— 需明确取舍
```

### 9.2 分阶段耗时（远端为主）

| # | 阶段 | 最快 | 预期 | 最坏 | 依据 / 备注 |
|---|---|---|---|---|---|
| 0 | **抢卡 + 开机** | 0.1 h | 0.3 h | **3 h** | 实测：今天 20 次连续失败(19 min)、早前 8 次失败(≈1 h)、也遇到过 57 次重试(2 h) |
| 1 | 环境校验（torch/peft/trl/bnb/基座/数据） | 5 min | 10 min | 25 min | 缺 causal_conv1d 会回退参考实现（只慢不挂） |
| 2 | 基座就位 | **0 min**（复用同一数据盘，base 52GB 已在） | 0 min | 88 min（需重传 52GB @9.8MB/s） | 关机不销毁数据盘 → 千万别释放实例 |
| 3 | GEN3 数据构建 + 上传 | 15 min | 35 min | 90 min | 本机建集 20 min（脚本首写 +60-120 min 一次性），上传 120MB ≈ 1 min |
| 4 | smoke 20 步 | 6 min | 8 min | 15 min | 首次 inductor 编译 112 s/步，之后 17-20 s |
| 5 | gate1 基座 LM loss | 2 min | 4 min | 10 min | 载 851 张量 ≈ 2 min + 2 条样本 |
| 6 | **训练 2,800 步** | 13.0 h | **14.5 h** | 18.0 h | A800 实测 18.2 s/step；5090 估 20-23 s（显存小、带宽相近）；bs2 有 OOM 风险需回落 bs1 → +30% |
| 7 | 取 adapter + 日志 + 关机 | 5 min | 8 min | 20 min | adapter 152MB @10MB/s ≈ 20 s |
| — | **远端小计** | **13.6 h** | **15.3 h** | **22.4 h** | 不含本机后处理 |

### 9.3 本机后处理（零机时，但要占人/占 GPU 时间窗）

| # | 阶段 | 预期 | 备注 |
|---|---|---|---|
| 8 | merge（分片，含 visual） | 2 min | 实测 1.9 min / 450MB/s，峰值 RAM < 6GB |
| 9 | gguf bf16 | 15 min | 54.6GB 落盘，judge8 抽样判据 |
| 10 | GSQ-RCO 配方 + IQ2_S 量化 | 10 min | 配方秒级，量化实测 4.3 min |
| 11 | 打包 .ninfer（text,vision,mtp） | 1 min | 实测 22-39 s |
| 12 | 12G 卡加载 + 行为验收三件套 | 20 min | 需 GPU 空闲；OxCoder 在跑时排队 |
| — | **本机小计** | **≈50 min**（+ 等 GPU） | 磁盘峰值需求 ≈ 160 GB |

### 9.4 突发情况清单（按概率 × 影响排序）

| 事件 | 概率 | 附加耗时 | 处置 |
|---|---|---|---|
| GPU 抢不到（机器被占） | 高 | +0.5~3 h | 循环重试 + 市场换机；实测今天 A800 20 连败 |
| 训练 bs2 在 32G 上 OOM | 中 | +30% 步时 | 立即回落 bs1/ga16（GEN2 已验证 21.9 GiB 稳） |
| 上传/下载被限速或 429 | 中 | +10~30 min | 8 流并行（封顶 9.8MB/s）；hf-mirror 429 时停并发改单流 |
| 实例数据盘只有 54GB | 中 | **直接失败** | 选 `max_instance_disk_size≥200GB` 的机型，否则换机 |
| 进程随会话回收 | 中 | +10~30 min | 一律 `setsid bash -c '...' < /dev/null &` |
| 断线/本机重启 | 中 | +10~40 min | 远端自治链 + 本机 `deadline_guard.sh`；传输全程 `--resume` |
| loss 平台或 gate 行为不达标 | 中 | +1~2 h | 追加 200-500 步或提负样本权重 1.5× |
| checkpoint 轮转丢点 | 低 | +0 | save-steps 200 + save-total-limit 4 + 手动快照 |
| causal_conv1d 缺失 | 高（已知） | +5~10% 步时 | 预装可省；不装也能跑（只慢） |
| 磁盘写满（云 200GB） | 低 | +30 min | 峰值：base 52 + ckpt 4×0.3 + adapter ≈ 55GB，安全 |

### 9.5 成本

| 机型 | 单价 | 远端 15.3 h（预期） | 最坏 22.4 h | 结论 |
|---|---|---|---|---|
| **RTX 5090 32G** | ¥2.88/h | **≈¥44** | ≈¥65 | 首选 |
| A800-80G | ¥7.98/h | ≈¥122 | ≈¥179 | 仅 5090 抢不到时用 |
| 真·两遍全量（5,786 步） | — | 5090 ≈¥88 · A800 ≈¥245 | — | 需明确是否要 |

> 数据盘按天计费（约 ¥0.05/GB·天量级），保留 200GB 盘 ≈ ¥10/天 —— 为省 88 min 重传，值得留一天。

---

## 10 执行结果（2026-10-30 已完成，与 §9 测算对照）

```text
状态      GEN3 训练 + 本地后处理全部完成；远端 5090 已 shutdown，计费停止
产物      train/lines/27b-kittyrev/local-pack/gen3/qwen3.8-27b-kittyrev-gen3-nsfw-gated-gsqrco-iq2s-txt-vis-mtp-2800s-9.6gb.ninfer
          9,924,500,224 B (9.925 GB) · text+vision+mtp · 1056 tensors
训练      2800/2800 步 · 9h49m20s · 12.11-12.63 s/step · loss 1.573 均值（末50 1.457）· acc 0.765
数据      GEN3 47,105 行（v2 + silver 净增 824）· 门控配对 100%
后处理    merge 1.7min → bf16 gguf → mmproj 928M → GSQ-RCO(9.40e9) → IQ2_S 9.61GB → pack 42s
          全程 CPU，未占用 GPU（OxCoder-9B 训练期间完成）
实际成本  5090 ¥2.88/h × 9h53m ≈ ¥28.5（§9 预期 ¥44，省 35%：步速 12.5s 优于估算 20-23s）

与 §9 测算偏差
  训练步速  实测 12.11-12.63 s/step，比 5090 估算(20-23s)快 40% —— 原因是 bs2/ga8 在 32G 上不 OOM 且 5090 带宽足
  数据规模  47,105 行（多算了 silver 净增 824），每 epoch 2,944 步，2800 步 = 0.951 遍
  唯一新增工作  5090 是 sm_120，机上 torch 2.6+cu124 不可用，需换 torch 2.9.1+cu128 + triton 3.5.1（+35 min）

后续待办见 train/logs/gen3-run-notes.md §6（引擎验收 / 门控评测 / 工具覆盖 / GEN2v2 A-B）
```
