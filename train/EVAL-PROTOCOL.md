# 评测规程（EVAL-PROTOCOL）

> 2026-10-28 立 · 本文件是「怎么评测才算数」的唯一口径
> 任何评测脚本、任何档位裁决、任何提速改动，都以此为准

---

## 0. 三条硬约束（违反即结果作废）

```
① 不降质量
   · 不压 max_new（当前 300）—— 压了会截断参数，把真实命中变成假 noarg
   · 不减评测条数 —— 12 条分辨率 8.3 pt、36 条 2.8 pt、40 条 2.5 pt，少于 30 条不能做档位裁决
   · 不用 batch 生成 —— 实测 batch=4 有 3/36 关键信息不同，batch=8 有 1/8
   · 不改 compute dtype（4bit dequant 用 bf16，换 fp16 会改数值）

② 不卡系统
   · 所有评测脚本先调 gpu_guard.apply()（VRAM 0.88 上限 / CPU 6 线程 / BelowNormal）
   · reserved 不得超物理显存 90%（11.91 × 0.9 = 10.72 GiB）
   · 前台有 Unity / 大程序时，不并行跑评测

③ 结果要可复现
   · 评测结果按「场景库 md5 + adapter 指纹 + max_new」缓存，键不一致就不复用
   · 每次评测落 JSON（含逐条 detail），不只留汇总数字
```

---

## 1. 判据体系（能力 vs 记忆度，两套指标不可混用）

### 1.1 能力（主判据）

| 阶段 | 脚本 | 指标 | 阈值 |
|---|---|---|---|
| **RE** | `eval_multi_adapter.py`（40 条） | 命中率（**工具+参数都对**）/ 编造 / 参数错 / 负向题 | ≥45% / ==0 / ≤8 / ≥3-of-4 |
| RE 粗筛 | 同上 `--cases 36` | 命中率（**只判工具名**） | ≥75% |
| **2A** | `eval_2a_sequence.py` | 首工具命中 / 前3交集 / 序列 LCS | ≥70% / ≥1.5 / ≥40% |
| **2B** | `nsfw_gate_eval.py` | GateRecall / GateLeak / GateFPR | ≥90% / ≤5% / ≤5% |
| **2C** | `eval_2c_longctx.py` | 长上下文损伤（裸问 vs 3000 tok 前缀） | ≤10 pt |

### 1.2 记忆度（辅助判据，只用来判断过拟合）

| 指标 | 脚本 | 健康 | 警告 | 停 |
|---|---|---|---|---|
| n-gram 20-gram 重合 | `eval_re_heldout.py` | <0.40 | 0.40–0.60 | >0.60 |
| 逐字复现条数 | 同上 | 0 | 1–2 | ≥3 |

**必须分清**：`eval_re_heldout.py` 从训练集抽样，**它是 in-sample 测试，测的是记忆度，不能用来判能力**（PITFALLS E4）。

---

## 2. 场景库演进（三份口径的教训）

| 版本 | 条数 | 判什么 | 发现的问题 |
|---|---|---|---|
| v1 | 12 | 工具名 | 1 条 = 8.3 pt，档2/档3 差 1 条就判「负增益」→ **纯噪声** |
| v2 | 36 | 工具名 | 12 条结论被推翻；但**完全没有参数维度** |
| **v3（当前）** | **40**（36 正向 + 4 负向） | **工具 + 参数 + 不该调工具** | 36 条的 75% 跌到 25%，**50 个百分点全是参数错** |

**三次排序结果完全不同**：

```
12 条：档2 91.7% > 档3 83.3% > 档1 50.0%
36 条：档3 75.0% > 档2 69.4% > 档1 58.3%
40 条：档1 27.5% > 档3 25.0% > 档2 22.5%
```

**结论**：口径决定结论。**任何档位裁决必须写明口径（条数 + 判什么）**，否则后人无法判断可信度。

---

## 3. 缓存机制

```
键 = 场景库 md5（id+ask 拼接） + adapter_model.safetensors 前 1MB 的 md5 + max_new
路径 = train/lines/9b-oxcoder/out/eval-cache/<key>.json
```

命中条件：三者全部一致。任何一项变了自动失效。

收益：

| 场景 | 耗时 |
|---|---|
| 首次跑 4 档 × 40 条 | ≈100 分钟 |
| 重跑同一批（缓存全命中） | **≈10 秒** |
| 只换一个 adapter | 只跑那一档 |

**这意味着**：改文档、改脚本、重看结果，只要 adapter 和场景库没动，立刻出结果。

---

## 4. 已否决的提速方案（附实测，勿重复尝试）

| 方案 | 实测 | 否决原因 |
|---|---|---|
| **batch 生成**（batch=4） | 加速 **3.03x**，但**关键信息不同 3/36**（8.3%） | 左 padding 改变 kernel reduce 顺序，4bit dequant 误差被放大 → 贪婪解码分叉 |
| **batch 生成**（batch=8） | 加速 3.16x，**1/8 关键信息不同** | 同上，且更长 |
| **causal_conv1d** | PyPI 全是源码包；无 nvcc/无 MSVC | pip 装不上；但 FLA+Triton 替身已打通（卷积 8.9–10x、packing 可用），见 [`CAUSAL-CONV1D.md`](CAUSAL-CONV1D.md)。仍占 forward **0.4%**、生成 **6.7%**，所以价值在 packing 不在卷积本身 |
| **flash-attn** | 未装，需 nvcc 编译 | 同上卡在无 CUDA Toolkit |
| **压 max_new 300→120** | 省约 60% | **会截断参数** → 制造假 noarg → 直接降质量 |
| **减评测条数到 24** | 省 40% | 分辨率从 2.5% 降到 4.2% → 降质量 |
| **fp16 compute** | 略快 | 4bit dequant 精度变，可能改数值 |

**唯一保留的提速**：缓存（重跑 100%）、预热（省 5–10 s 首次 kernel 编译）、`inference_mode`（2–5%）、`set_adapter` 单次加载（4 档省 4.5 分钟）。

---

## 5. 防卡顿（gpu_guard）

```python
import gpu_guard; gpu_guard.apply()
```

| 防护 | 值 | 防的是什么 |
|---|---|---|
| VRAM 硬上限 | 0.88 × 11.91 = **10.48 GiB** | 超了明确 OOM，不触发 WDDM 换页（PITFALLS D1：util 100% 但 power 53W，系统假忙） |
| CPU 线程 | 6 / 20 核 | OMP/MKL 默认吃满 20 核，与前台抢 |
| 进程优先级 | BelowNormal | 让 GUI / Unity 优先 |

环境变量可覆盖：`GUARD_VRAM_FRAC` / `GUARD_THREADS` / `GUARD_PRIORITY`。

**已接入**：`eval_multi_adapter.py` / `eval_re_generalize.py` / `eval_re_heldout.py` /
`eval_2a_sequence.py` / `eval_2c_longctx.py` / `verify_batch_equiv.py`（全部在 `load_model` 第一行）。

---

## 6. 标准操作流程

```bash
# ① 开训前/改数据后：一键体检
./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/health_check.py

# ② 记录基线（首次约 100 分钟，之后缓存秒回）
./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/eval_multi_adapter.py \
  --adapters "基座=,档1=train/lines/9b-oxcoder/out/re-stage1-fixed/final,档3=train/lines/9b-oxcoder/out/re-stage1-r2/final" \
  --out train/lines/9b-oxcoder/out/eval-40cases.json

# ③ 训练后：遍历 checkpoint 选优
./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/select_best_ckpt.py --run <out目录>

# ④ 改场景库后：先查泄漏
./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/check_eval_leak.py

# ⑤ 想改评测逻辑（并行/截断等）：先验等价性
./train/.venv/Scripts/python.exe -u train/lines/_shared/scripts/verify_batch_equiv.py --n 40 --batch 4
#   判据：关键信息不同必须 == 0
```

---

## 7. 结果落盘规范

| 文件 | 内容 |
|---|---|
| `train/lines/9b-oxcoder/out/eval-40cases.json` | 最新一次 40 条多档结果（含 detail） |
| `train/lines/9b-oxcoder/out/eval-cache/<key>.json` | 分档缓存（按 adapter + 场景库 + max_new） |
| `train/lines/9b-oxcoder/out/eval-2a-seq-*.json` | 2A 序列匹配 |
| `train/lines/9b-oxcoder/out/eval-2c-longctx.json` | 2C 长上下文损伤 |
| `train/logs/eval-*.log` | 原始日志（含逐条输出摘要） |

**必须包含逐条 detail**（`id / kind / got / fake / expect`），否则无法回溯某一条为什么错。

---

## 8. 自检清单（每次评测前）

```
[ ] 场景库版本与上次一致（否则缓存失效，且结论不可比）
[ ] 泄漏检查通过（check_eval_leak.py，最高相似 <0.55）
[ ] gpu_guard 已调用（日志里有 [guard] 行）
[ ] --batch 为 1（默认）
[ ] max_new 为 300（未压）
[ ] 前台无 Unity / 大程序在跑
[ ] 结果 JSON 含 detail
[ ] 汇报时写明口径（40 条 / 工具+参数 / 负向题）
```
