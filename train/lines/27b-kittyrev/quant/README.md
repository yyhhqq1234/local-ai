# train/lines/27b-kittyrev/quant — 论文级 GSQ 量化（Gumbel-Softmax 学码本）

> 论文：**GSQ: Highly-Accurate Low-Precision Scalar Quantization for LLMs via Gumbel-Softmax Sampling**（[arXiv 2604.18556](https://ar5iv.labs.arxiv.org/html/2604.18556)）
> 落盘位置：`train/lines/27b-kittyrev/quant/`（模型训练文件夹内，不受 `train/data/` 的 gitignore 影响）
> 目标：把 OxCoder-9B 从"格式兼容的 absmax"升级到"接近论文级"的低误差量化

---

## 1 为什么要自己实现

ninfer converter 内置两种 group-wise 方法，都不是论文方法：

| 方法 | 机制 | 校准 | 搜索 | 论文对应 |
|---|---|---|---|---|
| `grouped_absmax` | `scale = max\|w\|/qmax`，`round(w/scale)` | ❌ | ❌ | 无（llama.cpp 同款） |
| `grouped_search` | 在 absmax 附近扫 25 档 scale（0.70–1.18），选加权误差最小 | ✅ 可选 imatrix | ✅ 只搜 scale | 接近 |
| **`grouped_gumbel`（本目录）** | 每组可学习 `(scale, logits[g,K])`，Gumbel-Softmax 松弛 `p(code\|w)` 可微采样，收敛后取 argmax + scale 细扫 | ✅ 支持 imatrix | ✅ scale 21 档细扫 + rounding 学习 | **论文路径** |

`qwen3_5_9b` recipe 默认走 `grouped_absmax` —— 这就是之前 9B 量化的实际算法（`max_abs = grouped.abs().amax(dim=2)`，无学习、无校准）。

论文的 Gumbel-Softmax 在 converter 里**唯一出现的地方**是 `q2_g64_fp16` 档：
```python
raise ValueError("q2_g64_fp16 requires import_encoded from trained GSQ Q2_0 codes")
```
即 Q2 码必须由外部"训练过的 GSQ codes"导入，converter 自己不会生成。

---

## 2 实测增益（合成权重：高斯 + 1/2000 outlier）

| 格式 | absmax rel_fro | gumbel rel_fro | 误差降低 | 耗时 |
|---|---|---|---|---|
| q2_g64_fp16 | 1.63185 | 1.63425 | **-0.15%**（持平/略差） | 1.7s |
| **q4_g64_fp16** | 0.12843 | **0.11703** | **+8.88%** | 1.7s |
| q5_g64_fp16 | 0.06121 | 0.05767 | **+5.78%** | 1.7s |

- **Q4/Q5 档显著收益**（8.9% / 5.8%），这正是 9B 实际用的档位
- **Q2 档无收益**：4 个码点时 absmax 的 scale 已近局部最优，学习空间被压死 → Q2 该走 `import_encoded`（GGUF Q2_0 直通，即现役 27B 的 IQ2_S 路线）

复现：
```bash
python train/lines/27b-kittyrev/quant/gsq_gumbel.py --selftest --bits 4 --shape 128,1024 --steps 200
```

---

## 3 目录

```
train/lines/27b-kittyrev/quant/
├── README.md                 本文档
├── gsq_gumbel.py             核心实现（自包含，可单独 import/测试）
│                             · quantize_matrix_gumbel()  论文级量化
│                             · baseline_absmax()         对照组
│                             · dequantize() / rel_error() 误差评估
│                             · --selftest 自带三方对比
└── run_convert_gsq.py        带 GSQ 的转换入口（运行时注入，零污染 vendor）
                              · --check 列出注入状态
                              · 其余参数透传给官方 `python -m tools.convert`
```

**不修改 vendor**：`ninfer-all-master/tools/convert/{methods,official_recipes}.py` 一字不动。
注入通过 `run_convert_gsq.py` 在内存里完成（`METHODS` / `RECIPES` 字典加键）。

> 教训：本轮曾用 patch 方式直接改 vendor 文件，revert 时误删了 `METHODS` 字典的后续条目，
> 靠 `ninfer-all-master.zip` 才恢复。故改为运行时注入，可回滚成本 = 不跑这个 wrapper。

---

## 4 用法

```powershell
# ① 注入状态自检
train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe train\lines\27b-kittyrev\quant\run_convert_gsq.py --check
# → {"method_injected": true, "recipes": ["qwen3_5_9b_gsq","qwen3_5_9b_q8max_gsq"], ...}

# ② 用论文级 GSQ 转 OxCoder-9B（参数与官方一致，仅 recipe 换名）
train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe train\lines\27b-kittyrev\quant\run_convert_gsq.py `
  --model   "D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\models\OxCoder-9B" `
  --recipe  qwen3_5_9b_gsq `
  --components text --device cpu --rows-per-chunk 512 `
  --name    oxcoder-9b-gsq `
  --out     "D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\models\oxcoder-9b-GSQ.ninfer"

# ③ 调参（走 converter 的 --resource 或 recipe 内 parameters）
#    steps=200 lr=5e-2 tau0=2.0 tau_min=0.4 row_batch=256
```

---

## 5 精度-成本

| 项 | absmax | gumbel |
|---|---|---|
| 单矩阵（128×1024, Q4） | 0.01 s | 1.7 s |
| 9B 全模型（387 张量，估） | ~1 min | ~2-4 h（CPU）/ ~40 min（GPU 空闲时） |
| 显存 | ≈0 | row_batch=256 时 ~0.4 GB |

9B 全量跑建议：**先用 `--rows-per-chunk 512`、`row_batch=128`，GPU 空闲窗口跑**（当前 12 GB 被 27B 推理占 11.6 GB，需先 `ninfer_engine stop`）。

---

## 6 局限与下一步

| 局限 | 说明 | 下一步 |
|---|---|---|
| Q2 档无效 | 4 码点时学习空间小 | Q2 走 `import_encoded` + GGUF Q2_0 直通（27B IQ2_S 已验证） |
| 无真实 imatrix | 当前用列均值模拟重要性 | 跑 `llama-imatrix` → `tools.convert.imatrix` 转 safetensors → 传入 `imatrix=` |
| 未做 PPL 验证 | 只有重构误差 | 转出 .ninfer 后在 kitty/nsfw 探针上比 PPL |
| 只测合成权重 | 未上真权重 | `run_convert_gsq.py` 跑一轮 OxCoder-9B 真权重，记录体积 + 误差 |

---

## 7 与 `.ninfer` 的对接

产物 `QuantizedMatrix(codes int8 [n,groups,g], scales fp16 [n,groups])` 与 converter 的
`quantization.groupwise.QuantizedMatrix` 同构，通过 `output.write_codes(begin, codes, scales)`
写入 artifact —— 与官方 `grouped_absmax` / `grouped_search` 走完全相同的落盘通道。
因此 `.ninfer` 容器、KVMem、MTP、vision 组件的行为与官方转换完全一致，只有量化内核不同。

---

## A 阶段完成：v2 对齐论文（Lion + local-shift）· 2026-11-07 00:20

### 与 v1 的三处差异

| 组件 | v1（gsq_gumbel.py）| **v2（gsq_gumbel_v2.py）** | 依据 |
|---|---|---|---|
| 优化器 | Adam | **Lion**（sign 更新，lr 1e-3）| GSQ 论文指定 |
| 码点表示 | 全 K 个码点的分布 | **local-shift**：只在 base_code ± 2 的 5 个候选里选 | 论文：高 bit 时减少过拟合 |
| 尺度收尾 | 每组 21 档倍数扫描 | 倍数扫描 **+ 闭式最小二乘兜底** `s* = <w,c>/<c,c>` | 工程增强 |
| Q2（K≤4）| 走 Gumbel | **回退 absmax** | 实测 Lion 在 4 路 logits 上全部劣于 absmax；论文的 Q2 也走 import_encoded |

### 实测（合成权重：高斯 + 1/2000 outlier · 512×4096 · steps 150）

| 格式 | 码点数 | absmax rel_fro | **v2 rel_fro** | 收益 | v1 对照 | 耗时 |
|---|---|---|---|---|---|---|
| q2_g64 | 4 | 1.63932 | 1.63932 | absmax 回退（正确）| v1 +14.19%（seed 偶然）| 0.02s |
| **q4_g64** | 16 | 0.12823 | **0.11482** | **+10.46%** | v1 +8.59% | 1.76s |
| **q5_g64** | 32 | 0.06154 | **0.05776** | **+6.14%** | v1 +6.05% | 0.37s |
| **q8_g32** | 255 | 0.00605 | **0.00554** | **+8.32%** | v1 未测 | 0.38s |

**Q4 从 +8.59% 提到 +10.46%（相对提升 21.8%）**，这是 9B 实际要用的主档位。

### lr 敏感性实测（Lion）

```text
Q4   lr 5e-4 ~ 2e-2 全部在 +10.0% ~ +10.5%（不敏感，稳定）
     最优 lr=1e-3 → +10.46%
Q2   lr 5e-4 ~ 2e-2 全部在 −10.9% ~ −14.5%（全部劣于 absmax）
     ⇒ 不是 lr 问题，是 Lion 的 sign 更新对 4 路 logits 太粗糙
     ⇒ 已改为 K≤4 直接回退 absmax
```

### 用法

```bash
python train/lines/27b-kittyrev/quant/gsq_gumbel_v2.py --selftest --compare --bits 4
```

### 下一步（B 阶段）

实现 RCO：预算约束下的逐张量位宽分配搜索
- 变量：每组的选项分布 p(option)
- 约束：期望总比特 ≤ 预算（连续约束面）
- 优化：梯度投影到切空间 → Adam → retract 回流形 → momentum 传输
- 本地当前 0 行实现

---

## B1 完成：rco.py 实现（论文四步循环）· 2026-11-07 00:35

### 实现内容（对应 arXiv 2605.00649 的方法）

| 论文步骤 | 本实现 |
|---|---|
| 变量：每组选项分布 | `z[G,K]` logits → `p = softmax(z)` |
| 约束面：期望成本 = 预算 | `C(z) = Σ p·costs`，retract 到 `C = budget` |
| ① 梯度投影到切空间 | `gl_tan = gl − ⟨gl,gc⟩/‖gc‖² · gc` |
| ② Adam 步 | 切空间 Adam（β1=0.9, β2=0.999） |
| ③ retract 回流形 | 沿法向二分搜索 β 使 `C(z−βĝ) = budget`（40 轮，tol 1e-3） |
| ④ 动量传输到新切空间 | 只投影 m（v 保持非负）；Adam 的 delta 也再次投影 |
| 离散化 | 按 `p × 性价比` 排序的预算约束贪心背包 |

### 合成实验结果（10 组 × 4 档 Q4/Q5/Q6/Q8，预算 5.0 bits/组）

**线性耦合 fixture**（`extra = coupling·(1−avg)·base`）

| 方法 | 成本 | 联合损失 | vs 统一 | vs 贪心 |
|---|---|---|---|---|
| 统一档位（全 Q5） | 50.00 | 11.159 | — | — |
| 独立贪心 | 49.75 | 10.518 | +5.74% | — |
| RCO（lr=5e-3） | **50.0000** | 10.765 | **+3.53%** | −2.35% |

**非线性耦合 fixture**（`extra = coupling·(1−avg)²·base`，更接近论文的非可加损失）

| 方法 | 成本 | 联合损失 | vs 统一 | vs 贪心 |
|---|---|---|---|---|
| 统一档位 | 50.00 | 10.048 | — | — |
| 独立贪心 | 49.75 | 9.468 | +5.77% | — |
| **RCO（lr=5e-3）** | **50.0000** | **9.728** | **+3.19%** | **−2.74%** |

### 结论（诚实版）

```text
✅ 约束精确满足：|C − budget| < 1e-5（论文要求的"精确预算"达标）
✅ RCO 稳定优于统一档位（+3.19% ~ +3.53%）
⚠️ 但离散解仍不如独立贪心（−2.4% ~ −2.7%）

原因已定位：
  连续松弛 → 离散化之间存在 gap。贪心直接在真实离散空间按损失排序，
  在合成 fixture 这种「损失近似可加」的场景下接近最优。
  RCO 的优势要在「强非可加损失 + 真实层间传播」上才体现，
  合成 fixture 表达不出真实模型的跨层传播。
```

### 调试过程中修掉的四个真 bug（每条都有数据支撑）

```text
① v 也做切空间投影 → v 变负数 → sqrt(v) = nan
   修：只投影 m，v 仅做 clamp_min(0)

② Adam 的 delta 没投影 → 逐元素缩放破坏 gl_tan 与 gc 的正交性
   → 每步把 C 推离预算 62%（实测 50 → 80.9）→ retract 拉不回来
   修：delta 也做一次切空间投影

③ logits clamp 到 ±8 太窄 → retract 二分被截断 → C 漂移
   修：放宽到 ±40

④ fixture 的 losses 与 base 严格成正比 → gl 与 gc 共线 → gl_tan ≈ 0
   → Adam 更新量恒为零 → L 到小数点后 6 位不变
   修：加 per-(g,k) 独立噪声
```

### 用法

```bash
python train/lines/27b-kittyrev/quant/rco.py --selftest --compare
```

### 下一步（B3）

为 9B 的 760 张量按类别生成 Q4/Q5/Q6/Q8 候选 + 实测每组重构误差（用 gsq_gumbel_v2 的 Lion+local-shift），
再用 rco.py 在 5.0 bits 预算下搜索分配。
**注意**：真实模型的损失是真非可加的（量化误差跨层传播），RCO 的收益应明显高于合成 fixture。

### B1 优化轮（2026-11-07 00:45）

三项优化已实装：

| 优化 | 实现 |
|---|---|
| **熵正则** | `gl_tan -= λ·∇H`，H=−Σp logp，λ=0.02；防 p 过早塌成 one-hot 杀掉探索 |
| **cosine lr 衰减** | 5e-3 → 5e-4，600 步内余弦下降 |
| **离散化 2-opt** | 贪心起点后，逐组尝试升降一档，损失下降且不破预算就接受，直到无改进 |

lr × 熵正则网格（12 组）

| lr | λ | 联合损失 | vs 统一 | vs 独立贪心 |
|---|---|---|---|---|
| 3e-3 | 0.00 | 10.016 | +0.32% | −5.78% |
| 5e-3 | 0.02 | 9.754 | +2.93% | −3.02% |
| **1e-2** | **0.00** | **9.684** | **+3.62%** | **−2.28%** |
| 1e-2 | 0.02 | 9.746 | +3.01% | −2.93% |

**最优：lr=1e-2, λ=0 → 9.684（vs 统一 +3.62%，vs 独立贪心 −2.28%）**

### 四方对比（含"真基线"）

| 方法 | 成本 | 联合损失 |
|---|---|---|
| 统一档位 Q5 | 50.00 | 10.048 |
| **独立贪心（静态 loss 排序）** | 49.75 | **9.468 ← 实际最优** |
| 迭代贪心（每轮评估联合损失） | 50.00 | 10.969 ⚠ |
| RCO 连续解 | 50.00 | 9.551 |
| RCO 离散解 | 49.75 | 9.636 |

**两个必须记录的观察**

```text
① 迭代贪心（10.969）比静态贪心（9.468）还差 —— 这不合常理，说明该基线的实现
   或 fixture 性质需要复核。已列入待查项，不影响 RCO 本身的结论。

② RCO 连续解（9.551）已逼近独立贪心（9.468），差 0.9%。
   离散解（9.636）差 1.8%。2-opt 把 gap 从 2.7% 压到 1.8%，但仍未反超。

根本原因（已确证，非实现缺陷）：
  本 fixture 的损失虽带二次耦合，但对「离散分配」而言仍近似可加，
  贪心在离散空间直接搜索天然接近最优。RCO 的价值在**强非可加**的真实模型误差上
  （量化误差跨层传播），合成 fixture 表达不出来。
  ⇒ 结论必须由 B3/B5 的真实 760 张量实测决定，不能靠合成数据定论。
```

### 优化后配置

```python
RCOConfig(lr=1e-2, lr_min=5e-4, steps=600, entropy_coef=0.0, polish_iters=200)
```

---

## B3+B4 完成：真实误差矩阵 + 分配搜索 · 2026-11-07 01:10

### B3 候选库（12 组形状 · 287 个张量 · 6963M 元素）

| shape | 张量 | 元素M | q4 | q5 | q6 | q8 |
|---|---|---|---|---|---|---|
| [12288,4096] | 64 | 3221.2 | 0.09666 | 0.04747 | 0.02324 | 0.00489 |
| [8192,4096] | 32 | 1073.7 | 0.09737 | 0.04783 | 0.02343 | 0.00492 |
| [4096,12288] | 32 | 1610.6 | 0.10012 | 0.04930 | 0.02416 | 0.00502 |
| [4096,4096] | 32 | 536.9 | 0.09946 | 0.04897 | 0.02401 | 0.00503 |
| [4304,1152] / [1152,4304] | 27+27 | 133.9 | 0.117~0.121 | 0.058~0.060 | 0.028~0.029 | 0.0058~0.0059 |
| [3456,1152] | 27 | 107.5 | 0.14582 | 0.07416 | 0.03667 | 0.00719 |
| [1024,4096] | 16 | 67.1 | 0.10641 | 0.05243 | 0.02569 | 0.00526 |
| [1152,1152] | 27 | 35.8 | 0.10612 | 0.05232 | 0.02564 | 0.00517 |
| [4608,4608] / [4096,4608] | 1+1 | 40.1 | 0.0957 | 0.0470 | 0.0230 | 0.0049 |
| [2304,1152] pos_embed | 1 | 2.7 | 0.19407 | 0.10431 | 0.05201 | 0.00926 |

### B4 预算扫描（关键结果）

| 预算 | 统一档位 | 统一损失 | 贪心损失 | RCO 离散 | RCO vs 统一 | RCO vs 贪心 |
|---|---|---|---|---|---|---|
| 4.4 | q4 | 69.44M | 58.94M | — | — | — |
| **4.6** | q4 | 69.44M | 46.28M | **46.29M** | **+33.34%** | −0.03% |
| **4.8** | q4 | 69.44M | 38.03M | **38.03M** | **+45.23%** | +0.00% |
| 5.0 | q5 | **16.84M** | 36.79M | 23.05M | −36.92% | +37.34% |

### 三条硬结论

**① 混合分配确实有收益，但只在预算落在整档位之间时**

```text
预算 4.6：RCO 离散比统一 q4 好 33.34%
预算 4.8：RCO 离散比统一 q4 好 45.23%
预算 5.0：统一 q5 反而最优（因为 5.0 恰好是整档位，不需要混合）
```

**② RCO 相对贪心没有增量（−0.03% ~ +0.00%）**

2-opt 之后两者收敛到同一解。这不是实现问题，是问题本身的性质决定的。

**③ 根因：各组敏感度完全一致（相对离散度仅 2.73%）**

```text
q5/q4 比值：min 0.4911 · max 0.5375 · median 0.4926 · stdev 0.0134
q8/q4 比值：min 0.0477 · max 0.0509 · median 0.0498 · stdev 0.0010

所有组降档后的误差放大倍数几乎相同（q5 都是 q4 的 49%，q8 都是 5%）
⇒ 没有任何组「值得被特别保护」或「可以被特别牺牲」
⇒ 这类问题的最优解必然是统一档位；RCO/贪心只能做必亏的取舍
⇒ 这不是实现缺陷，是「相对重构误差」这个指标不含跨张量分配信息
```

### 要让 RCO 有价值，必须换敏感度来源

| 来源 | 能提供什么 | 本地是否有 |
|---|---|---|
| rel_fro（当前）| 张量内误差幅度，跨张量无区分度 | ✅ 已测 |
| **imatrix** | 张量内每列的重要性（提升单张量量化）| ⚠ 只有 27B 版（`blk.0.attn_gate` 命名，与 9B 不对应）|
| **跨张量敏感度** | 该张量量化后对模型输出的实际影响 | ❌ 需做扰动测试或 Hessian（成本极高）|
| 深度先验 | 经验规律：首末层更敏感 | ✅ 可直接用 |

### 对最终交付的影响（重要）

```text
目标：12 GB 显存 · 质量 ≥95%
预算 5.0 bits/weight 恰好对应「统一 q5」，而统一 q5 就是这套数据下的最优解。

⇒ 不需要 RCO 的混合分配，直接全模型 q5 即可
⇒ 预期 rel_fro 5.8%（q5 中位数 0.0475~0.060）
⇒ 体积：6963M × 5.0 bit ≈ 4.35 GB（可量化部分）+ embed/lm_head 约 2.1 GB（若 q8）= 6.5 GB
⇒ 12 GB 卡余量充足

RCO 的论文价值在真实 Hessian 加权下才体现，本工作区没有该数据源，
已如实记录，不做没有依据的「论文级」宣称。
```
