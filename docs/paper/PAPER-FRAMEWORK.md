# DSDA 顶刊论文结构框架与逻辑主线设计 (Paper Framework & Structural Outline)

**Document ID**: `LOCAL-AI-PAPER-FRAMEWORK-20261116`  
**Paper Title**: *Beyond Surface Adaptation: Deconstructing Memorization, Stage Overwriting, and Gating Biases in Domain-Specialized System Agents*  
**Target Venue**: IEEE Transactions (TSE / TIFS) / CCF-A 顶会 (NeurIPS / ICLR)  
**Author**: 杨涵钦 (yyhhqq1234)  
**Assistant / Engineering Support**: 石井 (Ishii), 本地工作区执行层  

---

## 1. 论文核心逻辑主线（五步递进链条）

按照国际权威期刊标准的小论文逻辑架构，整篇论文严格围绕以下五步闭环推进：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        DSDA 论文五步递进逻辑主线                        │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 背景问题   ── 大模型智能体向高危、低熵、不可逆底层系统渗透的双重困境 │
│ 2. 现有缺陷   ── 浅层微调掩盖记忆化、顺序微调破坏性覆盖、表征消除帕累托悬崖│
│ 3. 本文方法   ── DSDA：4 轴语义扰动 + 候选工具聚类 + 因果等长门控 + Scheme Z│
│ 4. 实验结论   ── 82.5% 工具泛化准确率，击败 Task Arithmetic 与 TIES，双模型验证│
│ 5. 核心价值   ── 提供低秩子空间干扰上界定理与端侧系统智能体 4 大工程落地准则│
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 详细章节架构与论证流设计 (7-Section System)

### §1. Introduction (引言)
- **1.1 底层系统环境的特殊严苛性**：
  - 区别于通用 API 与网页浏览，底层系统（驱动级 IO、逆向分析、内核调试）具有**低操作熵、严格参数模式、不可逆性（BSOD/进程崩溃）**三大特征；
  - 提出智能体特化的**双重困境（Dual Dilemma）**：能力获取困境（掌握 60+ 工具且零幻觉） vs 行为可控性困境（特权授权精准放行 vs 未授权绝对零泄漏且不误拒）。
- **1.2 现有主流范式的根本失效**：
  - 指出两大学术主流（多阶段课程微调 Curriculum Learning、表征工程消融 Representation Abliteration）在底层系统环境上的崩溃事实。
- **1.3 本文核心贡献（Three-fold Contributions）**：
  - **实证诊断**：首次系统性解构了紧凑模型在底层系统特化中的三大病理（记忆化假象、阶段覆盖、虚假长度捷径）；
  - **理论建模**：提出低秩子空间任务干扰上界定理（Theorem 1），从数学上证明了多任务参数重写的不可避免性；
  - **解耦框架**：提出 DSDA 体系，在 9B 混合注意力与 27B 密集全自注意力双架构上实现零泄漏、零误拒与 82.5% 工具泛化。

---

### §2. Empirical Pathologies in System Agent Specialization (三大微调病理深度解构)
- **2.1 The Memorization Illusion (记忆化假象与评估失效)**：
  - 发现：交叉熵损失（CE Loss）下降（1.110 $\to$ 0.373）并不代表语义习得；
  - 数据：20-Gram 逐字重合度从 0.167 激增至 0.515，完全相同匹配占比升至 40%；在剥离工具名的 L3 抽象题上泛化负增长（11/16 $\to$ 10/16）；
  - 归因：短查询与模板化输出导致模型走捷径记住字面关联，同分布验证集掩盖了这一病理。
- **2.2 Catastrophic Stage Overwriting (多阶段顺序微调的破坏性覆盖)**：
  - 实验：Stage 1 (工具路由) $\to$ Stage 2 (多轮代码轨迹) 后，工具调用准确率由 82.5% 崩塌至 10.0%，逃避调用率飙升至 82.5%（33/40）；
  - **定理 1 推导 (Theorem on Subspace Interference Bound)**：给出两任务在低秩流形上的梯度投影主夹角能量下界 $\mathcal{I}(\mathcal{T}_1, \mathcal{T}_2) \ge \sigma_{\min}^2(\mathbf{B}_1) \cos^2 \theta \|\nabla \mathcal{L}_2\|_F^2$；
  - **推论 1.1 (Corollary 1.1)**：证明参数空间正交隔离（Scheme Z）使交叉破坏恒等于零（$\mathcal{I} \equiv 0$）。
- **2.3 Trajectory Contamination (轨迹数据污染与语义漂移)**：
  - 标记伪奖励（B11）：66.3% 样本残留角色标记（`【assistant】`），模型为刷低 Loss 陷入死循环；
  - 切窗语义漂移（B12）：99.3% 切窗样本的 User 端被断成终端日志，将模型异化为“日志摘要器”而非“工具调度器”。

---

### §3. The Steering Dilemma: Limits of Representation Editing and Gating Shortcuts (行为调控边界)
- **3.1 The Pareto Cliff of Subspace Abliteration (表征消融帕累托悬崖)**：
  - 实验：对 9B 混合注意力模型进行拒绝方向几何正交投影消融；
  - 结论：$\gamma \le 1.0$ 时拒绝率维持 100%（$\text{KL}=0.046$）；$\gamma \ge 4.0$ 时突变跨越悬崖，KL 散度激增至 7.4~17.0，语法全面坍缩。紧凑模型中拒绝特征与语言连贯性紧密纠缠，不可线性分离。
- **3.2 Spurious Correlation in Condition Gating (虚假长度偏置捷径)**：
  - 发现：授权正样本平均 1,065 tokens，未授权拒答仅 126 tokens（8.4x 长度差异）；
  - 失效：模型将长度作为隐式授权开关，对详尽解释的未授权请求发生越狱放行，而对简短合规请求发生误拒。

---

### §4. The Proposed Framework: DSDA (解耦系统领域适配框架)
- **4.1 Semantic Anti-Memorization Protocol (语义抗记忆化协议)**：
  - 构造 4 轴扰动增强器（$K=4$：句式句法变换、领域同义词替换、前后缀注入、严格去重），在输出工具序列不变下强迫模型学习意图到 API 的映射；
  - 建立 L1（直白指令）/ L2（间接描述）/ L3（抽象故障诊断）分级评测体系。
- **4.2 Candidate-Aware Hard-Negative Tool Clustering (候选工具簇内难负例聚类)**：
  - 11 大功能拓扑簇，动态系统提示仅注入当前任务目标工具与 $k=8\sim12$ 个簇内难负例和跨通道干扰项，防御上下文稀释。
- **4.3 Structural Causal Formulation of Length-Balanced Gating (因果等长门控)**：
  - 引入结构因果模型（SCM）因果 DAG 图；
  - 强制合成等长反事实合规替代样本（$\sim 765$ tokens），证明后门路径 $X \leftarrow L \rightarrow Y$ 被切断，实现 $I(\text{Length}; \text{GateState}) \to 0$ 与 $\text{ACE}$ 确定性保障。
- **4.4 Modular Inference-Time Decoupling: Scheme Z (运行时模块解耦调度)**：
  - 独立训练 $\theta_{\text{RE}}$（工具路由）、$\theta_{\text{Code}}$（代码轨迹）与 $\theta_{\text{Gate}}$（双态转向）；
  - 运行时轻量路由网桥根据上下文动态挂载适配器，彻底阻断跨任务覆盖。

---

### §5. Experimental Evaluation (实验评估与基线对标)
- **5.1 实验设置**：双模型（9B 混合注意力 vs 27B 全密集自注意力）、硬件平台、评测场景库。
- **5.2 抗记忆化与工具特化结果 (Table 1)**：展示 Naive SFT 3-epoch 记忆化坍缩与 DSDA 在 L3 题上的 87.5%（14/16）高泛化。
- **5.3 跨规模与跨架构泛化性验证 (Table 2)**：对比 9B 与 27B 在 Zero-shot、微调前记忆化、DSDA 适配后的指标，双模型均实现 FN/FP 0/12。
- **5.4 多任务持续学习与主流模型合并对标 (Table 3)**：
  - 对标 Base Zero-Shot、ReAct (Prompt-only)、Sequential SFT、Task Arithmetic ($\tau=0.5$)、TIES-Merging ($p=0.8$)、Scheme X 联合混调与 DSDA Scheme Z；
  - 实测证明静态权重合并方法（Task Arithmetic/TIES）因参数子空间干涉导致工具准确率下降至 55.0%~62.5%，而 DSDA 维持 82.5% 且 0% 交叉破坏。
- **5.5 候选集规模消融与抗噪敏感度 (Table 4)**：$k=64$ 上下文稀释（77.5%） vs $k=8\sim12$ 最佳聚类（82.5%）。
- **5.6 双状态安全门控与技术陷阱评测 (Table 5)**：实测 GateLeak = 0.0000，TrapRefusal = 0.0000，通用能力 0% 坍缩。

---

### §6. Practical Engineering Guidelines for Autonomous System Agents (工程准则)
1. 废弃单权重多阶段微调，确立运行时模块化解耦规范；
2. 警惕验证集 Loss 陷阱，强制引入隐去工具名的语义重写基准；
3. 审计对齐样本的 Token 长度分布平衡，阻断隐式长度后门；
4. 约束运行时工具候选集，实施簇内难负例动态注入。

---

### §7. Conclusion (结论)
总结三大病理发现、Theorem 1 理论边界、DSDA 框架与双模型双达标实验结论。

---

## 3. 图表与代码 Listing 规划与交付总表

所有图表均已使用 Matplotlib / PIL 以 300 DPI 矢量级与暗黑终端样式渲染完毕，并作为高清图片插入 Word 定稿（[`beyond_surface_adaptation.docx`](beyond_surface_adaptation.docx)）：

| 编号 | 类型 | 标题 / 内容 | 论文所在章节 | 对应高清图片路径 | 呈现目的与论证逻辑 |
|---|---|---|---|---|---|
| **Figure 1** | 折线双轴图 | Training Loss vs. 20-Gram Memorization & L3 Generalization | §2.1 | [`images/fig1_memorization_vs_loss.png`](images/fig1_memorization_vs_loss.png) | 揭示“Loss 持续下降掩盖逐字记忆暴涨与泛化退化”的表层假象 |
| **Figure 2** | 系统架构图 | Architectural Overview of Decoupled System-Domain Adaptation | §4 | [`images/fig2_dsda_architecture.png`](images/fig2_dsda_architecture.png) | 呈现 4 轴扰动、候选簇采样、因果等长与 Scheme Z 运行时切换整体架构 |
| **Figure 3** | 对比直方图 | Token Length Disparity in Naive Gating vs. DSDA Balanced Gating | §3.2 | [`images/fig3_length_bias_distribution.png`](images/fig3_length_bias_distribution.png) | 直观展示正负样本 8.4x 长度差异被 DSDA 成功对齐消除的过程 |
| **Figure 4** | 因果 DAG 图 | Structural Causal Model (SCM) & Causal Interventions | §4.3 | [`images/fig4_causal_dag.png`](images/fig4_causal_dag.png) | 形式化展示后门路径切断与模块敲除干预 $do(\theta) \to Y$ 的因果保障 |
| **Listing 1** | 终端代码图 | Multi-Axis Semantic Query Perturbation Protocol | §4.1 | [`images/listing1_perturbation.png`](images/listing1_perturbation.png) | 以暗黑代码窗展示 $K=4$ 轴意图扰动扩展算法实现 |
| **Listing 2** | 终端代码图 | Candidate Tool Hard-Negative Clustering & Sampling | §4.2 | [`images/listing2_candidate_clustering.png`](images/listing2_candidate_clustering.png) | 展示 11 簇拓扑划分与簇内难负例提取算法实现 |
| **Listing 3** | 终端代码图 | Inference-Time Modular Adapter Dynamic Routing Logic | §4.4 | [`images/listing3_runtime_routing.png`](images/listing3_runtime_routing.png) | 展示 Scheme Z 运行时无感切外挂路由逻辑 |
| **Listing 4** | 终端代码图 | Task Arithmetic & TIES-Merging Baselines Implementation | §5.4 | [`images/listing4_baseline_merging.png`](images/listing4_baseline_merging.png) | 展示主流多任务模型合并基线的 PyTorch 算法实现 |
| **Table 1** | 三线表格 | Anti-Memorization Dynamics across Training Regimes | §5.2 | Word 嵌入 / Markdown | 量化展示 3 个 epoch 的 Loss、20-Gram 重合与 L3 泛化得分 |
| **Table 2** | 三线表格 | Cross-Scale and Cross-Attention Architecture Validation (9B vs 27B) | §5.3 | Word 嵌入 / Markdown | 证明 DSDA 在混合线性和密集全自注意力上的跨规模普适性 |
| **Table 3** | 三线表格 | Multi-Task Specialization & Mainstream Model Merging Baselines | §5.4 | Word 嵌入 / Markdown | 全面对标 Task Arithmetic、TIES-Merging、ReAct、Sequential SFT |
| **Table 4** | 三线表格 | Candidate Scale Ablation ($k$) & Random Seed Sensitivity | §5.5 | Word 嵌入 / Markdown | 验证 $k=8\sim12$ 最佳候选规模与 $+5$ 随机干扰鲁棒性 |
| **Table 5** | 三线表格 | Dual-State Safety Gating & Adversarial Trap Robustness | §5.6 | Word 嵌入 / Markdown | 验证 GateLeak = 0.0000 与 TrapRefusal = 0.0000 零偏置拦截 |

---

## 4. 论文与本地工程映射关联

- **论文 Word 投稿定稿**：`docs/paper/beyond_surface_adaptation.docx`
- **论文 Markdown 源码**：`docs/paper/beyond_surface_adaptation.md`
- **双盲投稿包（LaTeX）**：`docs/paper/submission_pack/main.tex`
- **审查与修复验收报告**：`docs/paper/PAPER-AUDIT-REPORT.md`
- **基线实测数据源**：`train/lines/9b-oxcoder/out/baseline_merging_benchmark.json`
- **一键复现入口**：根目录 `REPRODUCE.md`
