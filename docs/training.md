# 后训练

> 合并自：03-posttraining.md、06-posttraining-feasibility.md


---

## 03-posttraining.md

# 03 · 后训练计划

> 目录：`train/`｜既有说明：`train/README.md`（磁盘预算与串行流程）
> **可行性、显存数学、版本锁定、LoRA 挂载红线见 [`06-posttraining-feasibility.md`](06-posttraining-feasibility.md)**（依据备案包 `_research/微调能力-备案-20261020/`）
> 本文只回答"训练什么"（数据与验收）；"能不能训、怎么训"看 06。

## 1 目标

把本地模型在**工具使用与错误恢复**上的短板补进权重，减少对提示层约束的依赖。

当前靠提示/护栏兜住、但权重里没有的能力：

| 缺陷 | 现场证据 |
|---|---|
| 工具缺失仍硬做 | 41 步翻源码自造桥接（会话来 c4ea1e55 之前） |
| 收到明确错误指引仍穷举试参数 | 10 次 task-dispatch 变体（3197072f） |
| 目标达成不收手 | 模块数已拿到，仍折腾任务状态（3197072f / db680526 各残留 1-2 步） |
| 规格不达标即收工 | 要 3000 字给 1,800 |
| 反复自测 | health.sh 16 步 edit+wc -l、snake.py 9 步 |
| 单步思考过长 | medium 下仍见 7,285 字符 |

## 2 数据来源（已有）

| 文件 | 内容 |
|---|---|
| `_work/session-audit/s7.jsonl` | 42 条提示词包测试（去审查 6/6 通过、工具链 106 调用、鹈鹕落盘、推理陷阱 6 题） |
| `s8.jsonl` | kitty 32 步 abort（offload→read 递归） |
| `s9.jsonl` | kitty 22 步（task-dispatch 试错 10 次） |
| `s10.jsonl` | kitty 1044 步（熔断 finish=stop 死循环） |
| `s11.jsonl` | kitty **12 步 completed**（修复后基线） |
| `KITTY-ISSUE-BACKLOG.md` | 问题备案与后训练样本构造方向 |

解帧：`node _work/session-audit/unframe2.mjs <zstd> <out.jsonl>`

## 3 数据格式（计划）

```jsonl
// SFT（正样本：正确工具链 + 收尾）
{"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"...","tool_calls":[...]}],"meta":{"session":"s11","steps":12,"outcome":"completed"}}

// DPO（同一 prompt 的 chosen / rejected）
{"prompt":"...","chosen":"先 task-dispatch{type:finish} 再 task-close","rejected":"换 10 种 taskTransition 反复试","meta":{"session":"s9","steps":22}}
```

构造要点：
```text
· 每条样本带 steps 与 outcome，便于按"步数超标"加权
· rejected 侧保留模型原话（含它自己的 reasoning），让 DPO 学到"这种推理会走向空转"
· 负样本优先取：步数 >15、abort、连续 ERR 且参数结构相同
```

## 4 训练方案

```text
基座：Qwen3.8-27B（或 8B 替代做快速验证）
方法：QLoRA 4-bit + DPO
显存：12G 笔记本只能跑 8B 级 QLoRA；27B 需换机或云端
磁盘：见 train/README.md —— 27B 串行峰值 162G，base/merged/gguf 三者任一时最多并存两个
```

## 5 验收标准

```text
1) kitty 任务：同一提示词 ≤10 步完成，且不触发熔断、无 abort
2) 规格达标：3000 字任务输出 ≥2800 汉字或主动续写
3) 错误恢复：收到 ERR|EARLY-EXIT-DENY 后第一次动作就正确（不再换参数）
4) 自测纪律：同一文件回读 ≤1 次
5) 步数分布：p90 ≤15 步（当前 p90 约 22）
```

## 6 与提示层的关系

```text
提示层（executionRules 9 条 + 错误建议 + 告警/熔断）是"外骨骼"，后训练是"内化"。
目标：训练后可以逐步撤掉外骨骼里的 3/4/9 条，行为仍然正确。
撤除顺序：先撤单条 → 跑同一组验收 → 通过再撤下一条；失败即回滚该条。
```


---

## 06-posttraining-feasibility.md

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

详细命令见备案包 `04-RUNBOOK.md`（已含现成脚本：`train/lines/_shared/scripts/setup_env.ps1` / `fetch_base.py` / `train_qlora.py` / `merge.py`）。

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

---

## 13 更正（2026-10-21）：converter 并未丢失，且不需要 GGUF

原 §8 第 5 项「ninfer-v3 converter 本机已丢失 → 整条回炉链断」已过期。

| 项 | 更正后的事实 |
|---|---|
| converter 位置 | 上游 `Neroued/ninfer` 仓库 → `tools/convert/`（`python -m tools.convert`） |
| 获取方式 | GitHub 直连被墙，用 `ghfast.top` 代理拉源码 zip（实测 200，12.5 MB） |
| 输入格式 | **HF safetensors 检查点**（不是 GGUF），内置 recipe `qwen3_8_27b` 直接对标本项目架构 |
| 依赖 | Python 3.11 或 3.13 + PyTorch + NumPy；`--device cpu` 可纯 CPU 转 |
| 回炉链 | 合并 → `tools.convert` → `.ninfer`（**省掉 GGUF f16 中间件，省 54 GB 磁盘**） |
| 详情 | `train/lines/27b-kittyrev/kitty-rev/logs/CONVERTER-STATUS.md` |

结论：§8 的执行门槛从「1/4/5 三项」降为「1/4 两项」（训练栈 + 全精度基座），回炉链不再断。
