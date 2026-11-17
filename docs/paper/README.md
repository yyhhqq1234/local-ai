# DSDA 学术论文与制品包索引 (Research Paper & Artifacts)

> **论文作者与项目所有者**: 杨涵钦（yyhhqq1234，2923165556@qq.com）  
> 本目录归档了学术论文 **《Beyond Surface Adaptation: Decoupled System-Domain Adaptation and Causal Gating for Autonomous System Agents》** 的完整交付资产，涵盖 Word 定稿（含矢量图与暗黑代码块渲染）、Markdown 完整稿、标准 LaTeX 投稿包、高分辨率论文图表、基线对标数据以及匿名化可复现制品。

---

## 1. 论文核心资产清单

| 文件 / 目录 | 格式 / 形态 | 说明 |
|---|---|---|
| [`beyond_surface_adaptation.docx`](beyond_surface_adaptation.docx) | Word 格式 (940 KB) | **顶级期刊投稿定稿**：包含 IEEE/ACM 规范排版、三线表、300 DPI 矢量图与代码 Listing 终端渲染 |
| [`beyond_surface_adaptation.md`](beyond_surface_adaptation.md) | Markdown | 论文全量英文文本（包含 8 大章节、全部数学推导、定理 1、引理 1、推论 1.1、SCM 因果图、7 张数据表与 20 篇权威文献） |
| [`PAPER-FRAMEWORK.md`](PAPER-FRAMEWORK.md) | Markdown | **论文结构框架设计**：五步逻辑主线（背景问题 $\to$ 现有缺陷 $\to$ 提出方法 $\to$ 实验结论 $\to$ 核心价值）、8 章节详细规划与图表清单 |
| [`PAPER-AUDIT-REPORT.md`](PAPER-AUDIT-REPORT.md) | Markdown | **漏洞审查与修复验收报告**：针对 5 大漏洞在本项目中的实证真伪判定、修复举措与验收证明 |
| [`baseline_merging_benchmark.md`](baseline_merging_benchmark.md) | Markdown | **基线对标报告**：Task Arithmetic 与 TIES-Merging 模型合并在底层系统任务上的实测数据与理论分析 |
| [`generate_assets_and_docx.py`](generate_assets_and_docx.py) | Python 脚本 | 自动化图表绘制（300 DPI）与高保真 Word 论文生成器 |
| [`images/`](images/) | 目录 (PNG) | 论文高清插图（Figure 1~4）与暗黑终端代码图（Listing 1~4） |
| [`submission_pack/`](submission_pack/) | 目录 | **独立双盲投稿包**：包含 `main.tex`、`references.bib`、`METADATA.txt` 及离线复现脚本 `reproduce_eval.py` |

---

## 2. 论文章节框架与解耦主线对照 (8-Section Layout)

论文围绕「**三维解耦 (Decoupling)**」作为核心创新主线，贯穿 8 个完整章节：

```text
§1 Introduction ──→ §2 Related Work ──→ §3 Empirical Pathologies ──→ §4 Steering Dilemma
   (双重困境)          (5大分支对标)         (记忆化/阶段覆盖/干扰界)       (削减悬崖/虚假长度)
                                                      │
                                                      ▼
§8 Conclusion   ←── §7 Practical Guidelines ←── §6 Evaluation (Tables 2-7) ←── §5 DSDA Framework
   (全文收口)          (4条工程准则)              (5-Seed 统计/双架构/消融)        (语义/流形/因果解耦)
```

```text
┌─────────────────────────────────┬─────────────────────────────────┬─────────────────────────────────┐
│     发现的深层病理缺陷           │        DSDA 提出的解耦方法      │        论文关键实验与表项       │
├─────────────────────────────────┼─────────────────────────────────┼─────────────────────────────────┤
│ 1. 记忆化假象 (Memorization)    │ 语义解耦 (Semantic Decoupling)  │ Table 2: 20-Gram Overlap 0.210  │
│    (20-Gram 重合度暴涨至 0.515) │ 4 轴语义扰动扩展 (K=4) + L1~L3  │ L3 抽象题达 14/16 (87.5%, p<0.01)│
├─────────────────────────────────┼─────────────────────────────────┼─────────────────────────────────┤
│ 2. 阶段性能力覆盖 (Overwriting)  │ 流形解耦 (Manifold Decoupling)  │ Table 4: 优于 Task Arithmetic   │
│    (多阶段微调准确率跌至 10.0%) │ 定理 1 格拉斯曼子空间干扰下界   │ (55.0%) 与 TIES-Merging (62.5%) │
│    (相变式坍缩 82.5% -> 10.0%)  │ 运行时动态外挂解耦 (Scheme Z)   │ 消除干扰保持 82.5% ± 1.4% (I=0) │
├─────────────────────────────────┼─────────────────────────────────┼─────────────────────────────────┤
│ 3. 几何削减悬崖 (Abliteration)  │ 门控解耦 (Gating Decoupling)    │ Table 6: 避免 gamma>=4 语法崩溃 │
│    (gamma>=4 语言崩溃 KL > 17)  │ 参数隔离双状态独立外挂门控      │ 保留 100% 通用推理稳定性       │
├─────────────────────────────────┼─────────────────────────────────┼─────────────────────────────────┤
│ 4. 虚假长度捷径 (Length Bias)   │ 因果解耦 (Causal Decoupling)    │ Table 6: GateLeak = 0.0000      │
│    (正负样本 8.4x 长度差异)     │ 结构因果模型 (SCM) 反事实配对   │ TrapRefusal = 0.0000 (N=120)    │
│    (开门后门路径 X <- L -> Y)   │ 等长配对训练 (I(L; G) -> 0)     │ 彻底阻断后门欺骗路径            │
├─────────────────────────────────┼─────────────────────────────────┼─────────────────────────────────┤
│ 5. 跨架构与规模泛化性           │ 跨混合注意力和全自注意力        │ Table 3: 9B (OxCoder) 与        │
│    (避免单模型单一任务质疑)     │ 跨规模 (9B 与 27B) 完整验证     │ 27B (Qwen) 双架构实测通过       │
└─────────────────────────────────┴─────────────────────────────────┴─────────────────────────────────┘
```

---

## 3. 图表与清单资产全景 (Inventory)

### 3.1 高分辨率论文插图 (300 DPI)
- **Figure 1**: 训练交叉熵损失 vs. 20-Gram 词元逐字记忆化率与 L3 泛化动态 (`images/fig1_memorization_vs_loss.png`)
- **Figure 2**: 解耦系统领域适配框架 (DSDA) 总体系统架构图 (`images/fig2_dsda_architecture.png`)
- **Figure 3**: 传统安全微调 8.4x 长度偏置 vs. DSDA 反事实等长平衡分布 (`images/fig3_length_bias_distribution.png`)
- **Figure 4**: 结构因果模型 (SCM) 与模块化 $do$-演算干预图 (`images/fig4_causal_dag.png`)

### 3.2 终端暗黑代码块 (Terminal Code Listings)
- **Listing 1**: 多轴语义查询扰动生成算法 ($K=4$, `images/listing1_perturbation.png`)
- **Listing 2**: 候选工具难负例聚类采样协议 ($k=8\sim12$, `images/listing2_candidate_clustering.png`)
- **Listing 3**: 推理期模块化适配器动态路由器 (Scheme Z, `images/listing3_runtime_routing.png`)
- **Listing 4**: Task Arithmetic 与 TIES-Merging 基线模型合并算法 (`images/listing4_baseline_merging.png`)
- **Algorithm 1**: 反事实长度平衡对齐伪代码

### 3.3 论文主表矩阵 (Tables 1~7)
- **Table 1**: 病理现象、理论边界与 DSDA 解耦机制显式映射表
- **Table 2**: 训练体制下的抗记忆化动态与抽象泛化表现（5-Seed Mean $\pm$ Std, 95% CI, $p < 0.01$）
- **Table 3**: 9B 混合线性注意力 vs. 27B 全自注意力跨规模架构验证
- **Table 4**: 多任务模型合并与持续学习基线对标（Task Arithmetic, TIES-Merging, ReAct, DSDA Scheme Z）
- **Table 5**: 候选工具集规模 ($k$) 与抗噪敏感度消融评测
- **Table 6**: 扩展 $N=120$ 对抗性测试套件上的双状态安全门控与技术陷阱评测
- **Table 7**: 跨领域（HumanEval, SWE-bench Lite, BeaverTails）能力保留与泛化评测

---

## 4. 快速复现指引 (Artifact Reproduction)

对于审稿人或导师，可直接通过根目录的 `REPRODUCE.md` 指引或运行本目录下的轻量脚本：

```bash
# 1. 快速复现论文所有核心表格（Table 1 ~ Table 7，含 5-Seed 统计与 p 值）
train/.venv/Scripts/python.exe docs/paper/submission_pack/reproduce_eval.py

# 2. 现场复算 Task Arithmetic 与 TIES-Merging 模型合并对标数据
train/.venv/Scripts/python.exe scripts/run_baseline_merging.py

# 3. 重新渲染所有 300 DPI 图表并生成 Word 文档
train/.venv/Scripts/python.exe docs/paper/generate_assets_and_docx.py
```

---

## 5. 投稿系统表单预填 (Submission Metadata)

双盲投稿所需的标题、简短题目、TL;DR（<250字符）、纯文本格式摘要及学科分类已整备至：
[`submission_pack/METADATA.txt`](submission_pack/METADATA.txt)
可直接复制粘贴至 IEEE Author Portal、ACM ScholarOne 或 OpenReview 投稿系统。
