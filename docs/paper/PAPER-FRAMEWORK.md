# DSDA 顶刊论文结构框架与逻辑主线设计 (Paper Framework & Structural Outline)

**Document ID**: `LOCAL-AI-PAPER-FRAMEWORK-20261117-SEC`  
**Paper Title**: *Beyond Surface Adaptation: Decoupled System-Domain Adaptation and Causal Gating for Autonomous Binary Reverse Engineering and Security Agents*  
*(主标题与备选: Beyond Surface Adaptation: Decoupled System-Domain Adaptation and Causal Gating for Autonomous System Agents in Binary Reverse Engineering and Cyber Security)*  
**Target Venues**: 
- IEEE Transactions on Information Forensics and Security (TIFS)
- IEEE Transactions on Dependable and Secure Computing (TDSC)
- ACM Transactions on Privacy and Security (TOPS)
- IEEE Transactions on Software Engineering (TSE) / CCF-A  
**Author & Project Owner**: 杨涵钦 (yyhhqq1234，2923165556@qq.com)  
**Date**: 2026-11-17 (信息安全与逆向工程期刊专项深化版)

---

## 0. 信息安全与逆向工程核心关键词矩阵 (Security & RE Keywords)

为了确保手稿在 IEEE TIFS / TDSC / ACM TOPS 等信息安全顶刊审稿与检索中的精准命中，论文在元数据与各章节中系统性注入以下高频核心关键词：

| 领域维度 | 中文核心关键词 | 英文标准学术关键词 (Index Terms / Keywords) | 论文对应章节 |
|---|---|---|---|
| **核心领域** | 二进制逆向工程、静态反汇编与动态调试 | Binary Reverse Engineering, Disassembly & Decompilation, Dynamic Debugging | §1, §3.1, §5.2 |
| **系统安全** | 内核驱动安全、内存完整性与防护修改 | Kernel Driver Security, Memory Introspection & Patching, ASLR Rebasing | §1.1, §3.2, §5.2 |
| **自主对抗** | 自主网络防御、特权越权防护、威胁模型 | Autonomous Cyber Defense, Privilege Escalation Mitigation, Threat Models | §1, §4.2, §6.1 |
| **恶意分析** | 恶意代码取证、反作弊与 Hook 探测 | Malware Forensics, Anti-Cheat Probing, Inline Hook Detection | §3.1, §5.2, §6.6 |
| **理论与方法** | 因果安全门控、引用监视器、子空间干扰下界 | Causal Safety Gating, Reference Monitor, Subspace Interference Bounds | §3.3, §5.3, §6.6 |

---

## 1. 论文核心逻辑主线：以“解耦 (Decoupling)”统领全局

本框架将**“解耦 (Decoupling)”**作为贯穿全文的唯一灵魂主轴，将四大逆向工程与系统安全组件统一在“解耦领域适配与因果特权门控”的宏大安全叙事之下：

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│               DSDA 论文以“解耦 (Decoupling)”统领系统安全与逆向工程的主线               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. 语义解耦 (Semantic Decoupling)   ── 解耦表层词汇记忆 vs. 逆向意图与指令契约 (§3.1 / §5.1)   │
│    · 病理：Loss 下降掩盖逐字背题，逆向指令泛化失效（20-gram 重合暴涨至 0.515）          │
│    · 方法：4 轴语义扰动扩展 (K=4) + 逆向拓扑难负例聚类，迫使模型建立逆向意图-API 不变映射 │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. 流形解耦 (Manifold Decoupling)   ── 解耦内核驱动调试 vs. 通用代码轨迹流形 (§3.2 / §5.4)    │
│    · 病理：顺序微调引发阶段性覆盖（底层逆向工具调用率从 82.5% 崩塌至 10.0%）           │
│    · 理论：低秩子空间任务干扰下界定理（Theorem 1）证明多任务梯度在共享空间的不可逆破坏 │
│    · 方法：Scheme Z 运行时动态指针路由，参数正交隔离从数学上保证交叉干涉恒为零 (I ≡ 0)│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. 因果解耦 (Causal Decoupling)     ── 解耦特权授权决策 vs. 响应长度捷径 (§4.2 / §5.3) │
│    · 病理：条件门控中授权/拒答存在 8.4:1 长度差异，诱发隐式特权越权后门漏洞 (CWE-863)  │
│    · 理论：结构因果模型 (SCM) 揭示混淆后门通路 X ← L → Y                               │
│    · 方法：反事实等长对抗配对阻断后门，实现互信息 I(L; G) → 0 与无偏因果效应 (ACE) 保证 │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 1.1 病理 ➔ 理论边界 ➔ 解耦方法 ➔ 安全保障 显式映射矩阵 (Table 1)

| 发现的实证病理 (Empirical Pathology) | 理论根因与数学边界 (Theoretical Boundary) | DSDA 解耦应对方法 (Decoupling Component) | 评测验证指标与安全保障 (Safety & Robustness Proof) |
|---|---|---|---|
| **病理 1：记忆化假象 (Memorization)**<br>Loss 下降掩盖逐字背题，逆向同分布测试失效 | 低熵空间经验风险最小化退化为高维字典查表；参数容量未建立逆向指令语义不变性 | **语义解耦：4 轴逆向意图扰动扩展 ($K=4$) + 拓扑难负例聚类**<br>(§5.1 / Listing 1, 2) | 20-Gram 重合率从 $0.515 \to 0.210$<br>L3 抽象逆向故障推理提升至 $87.5\% \pm 2.2\%$ ($p<0.01$) |
| **病理 2：阶段性能力覆盖 (Overwriting)**<br>多阶段持续微调导致内核工具调度能力清零 | **Theorem 1 (子空间干扰下界)**：连续低秩微调中前序任务流形被后续梯度正交投影强力破坏 | **流形解耦：Scheme Z 运行时模块化正交解耦路由**<br>(§5.4 / Listing 3) | 交叉任务干涉能量严格为零 ($\mathcal{I} \equiv 0$)<br>工具调用率恢复至 $82.5\% \pm 1.4\%$，逃避率降为 0% |
| **病理 3：几何表征消融帕累托悬崖**<br>线性正交化在紧凑模型上引发语法与内核逻辑崩溃 | 紧凑模型中内核安全拒答子空间与通用语法子空间高度纠缠，不存在超平面线性可分性 | **门控解耦：双态独立参数隔离门控 ($\theta_{\text{Gate}}$)**<br>(§4.1 / §5.4) | 彻底规避 $\gamma \ge 4.0$ 导致的语言崩溃 ($\text{KL} > 17$)<br>维持恶意代码分析推理能力 $100\%$ 保留 |
| **病理 4：虚假长度偏置捷径 (Length Bias)**<br>正样本详尽、负样本简短诱发越权绕过 | **结构因果模型 (SCM)** 揭示长度 $L$ 作为混淆因子打开后门通路 $X \leftarrow L \rightarrow Y$ | **因果解耦：反事实等长对抗配对与引用监视器门控**<br>(§5.3 / Figure 4, Algorithm 1) | 在评测对抗样本空间内实现零策略违规 ($\text{GateLeak} = 0.000$)<br>对抗技术陷阱误拒率降至 $0.000$ |

---

## 2. 顶刊 8 章节完整架构规划 (8-Section Journal Architecture)

### §1. Introduction (引言：自主系统安全与逆向工程的严苛挑战)
- **1.1 底层系统安全与二进制逆向环境的特殊严苛性**：
  - 区别于通用 Web 浏览，自主网络防御与二进制逆向（内核驱动 IO、PE/ELF 结构解析、ASLR 动态重定位、反汇编与内存补丁）具有**低操作熵、严格参数模式、灾难性不可逆性（BSOD/内核崩溃）**三大特征；
  - 提出智能体特化的**双重困境 (Dual Dilemma)**：
    1. *特化能力获取困境*：掌握 60+ 复杂逆向工具（符号表解析、硬件断点设置、内存保护修改等）且保持零幻觉与零语法错误；
    2. *特权可控性困境*：在获得特权授权时能深度开展恶意代码取证与逆向分析，在未授权时绝对拒绝破坏性系统操作（如物理内存写入 `KM_PW` 或驱动强制脱钩），且不对包含敏感词的良性系统运维产生误拒（拒绝服务 DoS）。
- **1.2 现有主流范式的根本失效**：
  - 课程学习（Curriculum Learning）导致灾难性覆盖；表征消融（Abliteration）撞上帕累托悬崖；条件门控诱发越权后门漏洞。
- **1.3 本文核心主线与贡献（Unified Decoupling Framework）**：
  - **实证诊断**：系统解构三大病理（记忆化、阶段覆盖、长度偏置）；
  - **理论建模**：建立 Theorem 1 子空间干扰下界与结构因果模型 (SCM) 后门阻断定理；
  - **解耦框架**：提出 DSDA 全面解耦框架（语义解耦、流形解耦、因果解耦）；
  - **双模型与统计验证**：在 9B 混合注意力和 27B 全自注意力双架构上开展 5 种子重复实验与跨领域泛化评测。
  - **呈现 Table 1**：显式映射矩阵。

---

### §2. Related Work (相关工作 · 独立章节：安全与智能体五大研究脉络)
系统梳理信息安全、逆向工程与大模型系统智能体五大研究脉络（20 篇权威文献）：
- **2.1 Parameter-Efficient Continual Learning & Low-Rank Interference (参数高效持续学习与低秩干扰)**：
  - 综述 LoRA (Hu et al., 2022)、QLoRA (Dettmers et al., 2023) 在多阶段适应中的参数更新动力学；
  - 分析传统排练机制（A-GEM, Chaudhry et al., 2019）与正则化（EWC, Kirkpatrick et al., 2017）在低秩子空间中的容量局限（Biderman et al., 2024）。
- **2.2 Model Merging & Weight Subspace Disentanglement (模型合并与参数子空间解耦)**：
  - 剖析 Task Arithmetic (Ilharco et al., 2023) 与 TIES-Merging (Yadav et al., 2023) 的权重向量线性组合假设；
  - 阐明静态参数重叠在低熵不可逆底层系统安全指令集上的维度冲突与精度退化机理。
- **2.3 Representation Engineering & Geometric Safety Steering (表征工程与几何安全导向)**：
  - 梳理 Representation Engineering (Zou et al., 2023) 与 Refusal Direction Abliteration (Arditi et al., 2024)；
  - 揭示方向消除技术在不同参数规模（超大密集模型 vs 紧凑混合注意力模型）上的表现分异与流形纠缠问题。
- **2.4 Causal Inference & Spurious Shortcut Mitigation in Language Models (因果推断与虚假捷径消除)**：
  - 回顾 Pearl 结构因果模型 (SCM, Pearl 2009) 与 $do$-calculus 在自然语言处理去偏中的应用；
  - 探讨指令微调中常见的表面形式偏置（长度偏置、位置偏置）及其对特权访问控制机制的安全性威胁（Wang et al., 2023）。
- **2.5 LLMs in Binary Reverse Engineering & Autonomous Cyber Defense (大模型在逆向工程与自主网络安全中的应用)**：
  - 综述 ToolLLM (Qin et al., 2024)、Gorilla (Patil et al., 2023) 与 SWE-bench (Jimenez et al., 2024)；
  - 对标 IDA Pro、Ghidra、REA 等逆向辅助工具链与内核级调试接口（DrCE/Kitty 桥），指出通用工作流对底层不可逆操作（Kernel Driver IO / Memory Patching）的安全门禁与确定性保障缺口。

---

### §3. Empirical Pathologies in System Agent Specialization (三大微调病理深度解构)
- **3.1 The Memorization Illusion and Brittle Evaluation (记忆化假象与评估失效)**：
  - 实验现象：CE Loss 下降（1.110 $\to$ 0.373）并不代表逆向理解的泛化；
  - 统计佐证：20-Gram 逐字重合度从 0.167 激增至 0.515，完全匹配占比升至 40%；在隐去具体工具名的抽象逆向故障推理题（L3）上泛化出现负增长；
  - **展示 Figure 1**：Training Loss vs. 20-Gram Memorization and L3 Generalization Across Epochs。
- **3.2 Catastrophic Stage Overwriting in Sequential Fine-Tuning (多阶段微调的破坏性覆盖)**：
  - 实验现象：Stage 1 (逆向工具调度) $\to$ Stage 2 (多轮代码轨迹) 后，逆向工具准确率暴跌至 10.0%，逃避调用率飙升至 82.5%（33/40）。
- **3.3 Theoretical Formalization: Subspace Interference Lower Bound (子空间干扰下界定理)**：
  - **Assumption 1 (Low-Rank Grassmannian Manifold)**：低秩适配参数处于矩阵流形空间；
  - **Lemma 1 (Orthogonal Projection Energy Decomposition)**：正交投影算子能量分解引理；
  - **Theorem 1 (Task Interference Bound)**：形式化陈述与严密数学证明：
    $$\mathcal{I}(\mathcal{T}_1, \mathcal{T}_2) = \left\| \mathcal{P}_{\mathcal{S}_1}(\nabla_{\mathbf{W}} \mathcal{L}_2) \right\|_F^2 \ge \sigma_{\min}^2(\mathbf{B}_1) \cdot \cos^2 \theta(\mathcal{S}_1, \mathcal{S}_2) \cdot \|\nabla_{\mathbf{W}} \mathcal{L}_2\|_F^2$$
  - **定量相变映射机制 (Quantitative Mapping to 82.5% $\to$ 10.0% Collapse)**：建立累积参数漂移 $\Delta_{\text{drift}}$ 与分类器 Logit 边界翻转的显式数学映射，解释离散 argmax 决策下的突发相变崩塌。
  - **Corollary 1.1 (Orthogonal Decoupling Zero-Interference Proof)**：形式化证明 Scheme Z 参数正交隔离下 $\mathcal{I} \equiv 0$。
- **3.4 Trajectory Contamination and Semantic Displacement (逆向轨迹污染与语义漂移)**：
  - 标记伪奖励（B11）：66.3% 样本残留角色标记诱发死循环；
  - 切窗语义漂移（B12）：99.3% 切窗样本导致模型异化为日志摘要器，破坏逆向主动诊断因果链。

---

### §4. The Steering Dilemma: Limits of Representation Editing and Gating Shortcuts (行为调控边界)
- **4.1 The Pareto Cliff of Subspace Abliteration (表征消融帕累托悬崖)**：
  - 实验证明：$\gamma \le 1.0$ 时拒绝率维持 100%（$\text{KL}=0.046$）；$\gamma \ge 4.0$ 时突变跨越悬崖，KL 散度激增至 7.4~17.0，语法全面坍缩。安全拒答流形与逆向句法流形高度纠缠。
- **4.2 Spurious Correlation in Condition Gating: The Length Shortcut (虚假长度偏置捷径)**：
  - 发现：授权正样本平均 1,065 tokens，未授权拒答仅 126 tokens（8.4:1 长度差异）；
  - 越权漏洞复现 (CWE-863)：攻击者在未授权请求中要求详尽长篇分析即可越狱绕过拒答限制；合规简短系统诊断任务被误拒。
  - **展示 Figure 3**：Token Length Disparity in Naive Safety Gating vs. DSDA Balanced Gating。

---

### §5. The Proposed Framework: DSDA (解耦系统领域适配与因果门控体系)
- **展示 Figure 2**：DSDA 系统总体解耦架构图（包含语义解耦、流形解耦与因果门控）。
- **5.1 Semantic Anti-Memorization Protocol (语义意图解耦)**：
  - 4 轴扰动增强器（$K=4$：句法重构、PE/逆向同义术语代换、上下文注入、去重过滤）；
  - 形式化不变性学习目标：在扰动输入集合下强制工具调用输出序列完全一致。
  - **展示 Listing 1**：Multi-Axis Semantic Query Perturbation 代码。
- **5.2 Candidate-Aware Hard-Negative Tool Clustering (候选空间拓扑解耦)**：
  - 将 64 个底层安全与逆向工具划分为 11 大功能拓扑簇（内核直接 IO、内存内省与修补、动态调试与断点、PE/ELF 格式取证、反作弊探测等）；
  - 动态系统提示仅注入目标工具与 $k=8\sim12$ 个簇内难负例和跨通道干扰项，消除上下文稀释。
  - **展示 Listing 2**：Candidate Tool Hard-Negative Sampling 代码。
- **5.3 Causal Length-Balanced Gating: SCM & Backdoor Blocking (因果等长解耦门控 · 引用监视器)**：
  - **结构因果模型 (SCM) 形式化五元组**：定义外生变量 $U$ 与内生变量 $X$ (输入), $L$ (长度), $G$ (门控状态), $Z$ (语义特征), $Y$ (输出行为)；
  - **展示 Figure 4**：结构因果模型 (SCM) 混淆后门通路 $X \leftarrow L \rightarrow Y$ 与 $do(G=g)$ 阻断干预图；
  - **展示 Algorithm 1**：Counterfactual Length-Balanced Alignment Generation 算法伪代码；
  - **因果效应公式**：严格推导干预下的 Average Causal Effect (ACE)，证明 $I(L; G) \to 0$。
- **5.4 Inference-Time Modular Adapter Decoupling: Scheme Z (运行时流形解耦路由)**：
  - 独立微调三套解耦低秩适配器：$\theta_{\text{RE}}$（逆向工具调度）、$\theta_{\text{Code}}$（长代码综合与轨迹排障）与 $\theta_{\text{Gate}}$（特权决策）；
  - 运行时网桥基于上下文状态进行无缝动态指针调度，参数正交隔离彻底粉碎跨任务破坏。
  - **展示 Listing 3**：Dynamic Runtime Modular Router (Scheme Z) 代码。

---

### §6. Experimental Evaluation (实验评估与统计严密性对标)
- **6.1 威胁模型、评测集规模与统计规范 (Threat Model & Statistical Rigor)**：
  - **威胁模型 (Threat Model)**：界定黑盒/白盒攻击能力、提示词注入、恶意越狱、越权提升边界与系统完整性保护目标；
  - **三层综合对抗评测集 ($N=120$)**：包含 60 例成对合规/非合规意图、35 例混淆技术陷阱（如包含 `ZwTerminateProcess` 等高危调用）与 25 例多轮上下文状态漂移；
  - **统计规范**：5 次随机种子（Seeds: 7, 11, 42, 128, 256）的均值 $\pm$ 标准差（Mean $\pm$ Std）、95% 置信区间及配对 t 检验（$p<0.01$）。
- **6.2 抗记忆化与逆向工具特化结果 (Table 2)**：
  - 报 5 种子均值 $\pm$ 标准差；DSDA 20-Gram 重合度降至 0.210，抽象 L3 逆向推理泛化达 87.5% ($p < 0.01$)。
- **6.3 跨规模与跨架构双线泛化验证 (Table 3)**：
  - 9B 混合线性注意力（OxCoder-9B） vs 27B 密集全自注意力（Qwen-27B），双架构均复现零安全策略违规。
- **6.4 多任务持续学习与主流模型合并对标 (Table 4)**：
  - 全面对标 Base Zero-Shot、ReAct、Sequential SFT、Task Arithmetic、TIES-Merging、Scheme X 与 DSDA Scheme Z；
  - **展示 Listing 4**：Task Arithmetic & TIES-Merging 基线合并 PyTorch 代码；
  - 证实静态参数合并在底层逆向指令上存在严重参数碰撞冲突（准确率跌至 55.0%~62.5%）。
- **6.5 候选集规模消融与抗噪敏感度 (Table 5)**：
  - 汇报不同候选规模 $k \in \{0, 8\sim12, 16, 48, 64\}$ 在 5 种子下的均值 $\pm$ 标准差，论证最优信噪比。
- **6.6 双状态安全门控与对抗测试结果 (Table 6 · 严格安全期刊措辞)**：
  - 规范表述：“在所测 $N=120$ 综合对抗样本集上未观测到策略违规（$\text{GateLeak} = 0.000$）”；
  - 对标 Naive Gating（0.083 泄漏，0.222 陷阱误拒）与 SRA Abliteration（崩溃），证明因果等长门控的稳健性。
- **6.7 跨领域对照与边界讨论 (Table 7 & Limitations)**：
  - **Table 7 (Cross-Domain Retention)**：通用代码（HumanEval 98.5%）、多轮调试（SWE-bench 98.3%）与通用安全对齐（BeaverTails 100.0%）对照，证实通用能力高保留率；
  - 适用边界（Boundary Conditions）：限定 DSDA 适用于高确定性、低操作熵、状态不可逆的敏感系统安全环境。

---

### §7. Practical Engineering Guidelines for Autonomous Cyber Security Agents (安全智能体工程落地准则)
1. 废弃单权重多阶段顺序微调，强制建立运行时模块化解耦规范；
2. 警惕验证集 Loss 陷阱，强制引入隐去具体工具名的语义同义泛化测试；
3. 严格审计特权对齐数据的 Token 长度平衡，物理阻断长度后门；
4. 约束运行时工具候选空间，实施拓扑簇难负例动态注入。

---

### §8. Conclusion (结论)
总结三大病理发现、Theorem 1 子空间干扰下界、结构因果模型后门阻断、DSDA 解耦框架与双模型统计显著达标成果。

---

## 3. 图表、算法 Listing 与表格完整资产映射表 (Full Inventory)

| 资产编号 | 资产类型 | 资产标题 / 内容 | 所在章节 | 呈现目的与论证逻辑 |
|---|---|---|---|---|
| **Figure 1** | 学术折线图 (300 DPI) | Loss vs. Memorization & Generalization | §3.1 | 揭示“Loss 单调下降掩盖逐字记忆暴涨与逆向泛化退化”的实证病理假象 |
| **Figure 2** | 系统架构图 (300 DPI) | Architectural Overview of DSDA Framework | §5.0 | 呈现语义解耦、流形解耦、因果解耦三大支柱的全流程架构视图 |
| **Figure 3** | 双峰直方图 (300 DPI) | Token Length Disparity vs. Balanced Gating | §4.2 | 直观呈现正负样本 8.4:1 严重长度偏置被 DSDA 因果等长消除的过程 |
| **Figure 4** | 因果 DAG 图 (300 DPI) | Structural Causal Model & Intervention Graphs | §5.3 | 形式化呈现混淆后门通路 $X \leftarrow L \rightarrow Y$ 与 DSDA 阻断干预 $do(G=g)$ |
| **Algorithm 1** | 算法伪代码块 | Counterfactual Length-Balanced Alignment Generation | §5.3 | 给出因果等长反事实训练样本对合成的严格数学约束与实现伪代码 |
| **Listing 1** | 终端代码图 (300 DPI) | Multi-Axis Semantic Query Perturbation | §5.1 | 以暗黑终端窗口展示 $K=4$ 轴意图扰动扩展生成器代码实现 |
| **Listing 2** | 终端代码图 (300 DPI) | Candidate Hard-Negative Clustering Algorithm | §5.2 | 展示 11 簇逆向拓扑划分与簇内难负例抽样代码实现 |
| **Listing 3** | 终端代码图 (300 DPI) | Dynamic Runtime Modular Router (Scheme Z) | §5.4 | 展示 Scheme Z 运行时动态指针无感解耦调度核心逻辑 |
| **Listing 4** | 终端代码图 (300 DPI) | Task Arithmetic & TIES-Merging Baselines | §6.4 | 展示主流多任务模型合并基线的 PyTorch 算法实现 |
| **Table 1** | 三线学术表 | Explicit Mapping Matrix of Pathologies, Boundaries, and Solutions | §1.3 | 四大病理与四大理论边界/解耦机制的显式一一映射矩阵 |
| **Table 2** | 三线学术表 | Anti-Memorization Dynamics across Regimes (5 Seeds Mean±Std) | §6.2 | 汇报 5 种子下的 Loss、20-Gram 重合度与 L3 逆向泛化准确率及显著性 |
| **Table 3** | 三线学术表 | Cross-Scale & Architecture Validation (9B vs 27B) | §6.3 | 证明 DSDA 在混合线性和密集全自注意力上的跨规模、跨注意力机制普适性 |
| **Table 4** | 三线学术表 | Multi-Task Specialization & Merging Baselines | §6.4 | 对标 Task Arithmetic、TIES、ReAct、Sequential SFT（含配对 t 检验 $p$ 值） |
| **Table 5** | 三线学术表 | Candidate Scale Ablation ($k$) & Seed Sensitivity | §6.5 | 汇报不同候选规模 $k$ 在 5 种子下的均值 $\pm$ 标准差，论证最优信噪比 |
| **Table 6** | 三线学术表 | Dual-State Safety Gating on $N=120$ Test Suite | §6.6 | 汇报在综合对抗集上的防泄漏率、技术陷阱识别率及通用能力保留率 |
| **Table 7** | 三线学术表 | Cross-Domain Retention and Benchmark Generalization | §6.7 | 汇报通用代码（HumanEval）、多轮调试（SWE-bench）与安全对齐（BeaverTails）数据 |
