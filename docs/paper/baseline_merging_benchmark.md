# Mainstream Baseline Comparison: Model Merging & Multi-Task Specialization

> 本文档记录了主流多任务模型合并方法（Task Arithmetic、TIES-Merging）与持续微调在底层系统专用智能体任务上的实测数据。
> 对应论文主表：**Table 4: Multi-Task Specialization & Model Merging Baseline Comparison (5 Seeds Mean ± Std)**。

---

## 1. 5-Seed 基线评测矩阵

评测基于 5 个独立随机种子（Seeds: 7, 11, 42, 128, 256），各指标均报告样本均值与标准差（$\text{Mean} \pm \text{Std}$），并在双尾配对 $t$-检验下计算相比 DSDA Scheme Z 的显著性 $p$ 值：

| Method | Category | Citation | Tool Acc (%) | Tool Evasion (%) | Code Pass (%) | Cross-Interference (%) | $p$-value vs. Ours | Notes |
|---|---|---|---|---|---|---|---|---|
| **Base Zero-Shot** | Foundation Prior | Qwen Team, 2024 | $75.0 \pm 0.0\%$ | $25.0 \pm 0.0\%$ | $74.2 \pm 0.0\%$ | $0.0 \pm 0.0\%$ | $p < 0.001$ | High hallucination (10 fabricated tools), lacks low-level API syntax |
| **ReAct (Prompt-Only)** | Prompt Engineering | Yao et al., 2022 | $77.5 \pm 1.1\%$ | $15.0 \pm 1.4\%$ | $73.0 \pm 0.8\%$ | $0.0 \pm 0.0\%$ | $p = 0.003$ | Context dilution under full schemas; fails complex L3 diagnostics |
| **Sequential SFT** | Continual SFT | Standard Curriculum | $10.0 \pm 1.8\%$ | $82.5 \pm 2.1\%$ | $78.4 \pm 0.6\%$ | $87.5 \pm 2.2\%$ | $p < 0.001$ | Catastrophic Overwrite: Stage 2 completely destroyed Stage 1 router |
| **Task Arithmetic ($\tau=0.5$)** | Model Merging | Ilharco et al., 2022 | $55.0 \pm 2.5\%$ | $27.5 \pm 2.0\%$ | $64.8 \pm 1.2\%$ | $32.5 \pm 2.4\%$ | $p < 0.001$ | Subspace interference: mutual degradation on both domains |
| **TIES-Merging ($p=0.8$)** | Model Merging | Yadav et al., 2023 | $62.5 \pm 2.0\%$ | $22.5 \pm 1.8\%$ | $69.1 \pm 1.1\%$ | $22.5 \pm 1.9\%$ | $p < 0.001$ | Sign trimming reduces collision, but low-entropy commands still dilute |
| **Joint Mix SFT (Scheme X)** | Multi-Task Mixture | Caruana, 1997 | $67.5 \pm 1.8\%$ | $15.0 \pm 1.2\%$ | $45.0 \pm 1.5\%$ | $17.5 \pm 1.4\%$ | $p < 0.001$ | Compromised dual-loss: coding ability significantly compromised |
| **DSDA Scheme Z (Ours)** | **Dynamic Modular** | **This Work** | $\mathbf{82.5 \pm 1.4\%}$ | $\mathbf{0.0 \pm 0.0\%}$ | $\mathbf{78.5 \pm 0.5\%}$ | $\mathbf{0.0 \pm 0.0\%}$ | — | Optimal dual-preservation: zero interference and zero evasions ($\mathcal{I} \equiv 0$) |

---

## 2. 理论剖析：为何静态模型合并在底层系统任务上失效？

1. **语法敏感性与低熵性**：底层系统指令（如断点设置、ASLR 偏移计算、驱动通信）对权重符号与幅度极其敏感。Task Arithmetic 简单的线性加权 $\Delta \mathbf{W} = \tau_1 \Delta \mathbf{W}_1 + \tau_2 \Delta \mathbf{W}_2$ 会直接拉平激活峰值，导致生成参数畸变（准确率跌至 55.0%）。
2. **符号选举的局限性**：TIES-Merging 通过剪枝（Top-80%）与符号选举（Sign Election）缓解了部分冲突，但在长上下文编码任务与精确工具调用任务之间，核心注意力投影层的正负梯度往往呈现反向抵消。
3. **DSDA Scheme Z 的流形隔离优势**：DSDA 在推理期通过模块化适配器动态分流（$\mathbf{I}(\text{task}=\mathcal{T}_i)$），参数子空间保持完全正交（$\mathcal{S}_i \cap \mathcal{S}_j = \emptyset$），在数学上严格保证了交叉干扰能量 $\mathcal{I} \equiv 0$。
