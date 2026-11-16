# Local-AI 文档体系总览 (Documentation Map)

本目录归档了 Local-AI 项目从**工程架构落地**、**后训练与微调实验**、**模型运维与切换**到**学术研究与论文发表**的完整文档链条。

---

## 1. 核心文档导航矩阵

```text
docs/
├─ paper/              ← 【学术研究与论文专区】
│  ├─ README.md        ← 论文资产清单与实验表项速查
│  ├─ beyond_surface_adaptation.docx  ← 论文 Word 最终投稿定稿 (658 KB)
│  ├─ beyond_surface_adaptation.md    ← 论文 Markdown 完整源码（含定理推导与公式）
│  ├─ PAPER-FRAMEWORK.md              ← 论文结构框架设计（五步逻辑主线与7章节规划）
│  ├─ PAPER-AUDIT-REPORT.md           ← 漏洞完全性审查与修复验收报告（实证真伪判定与闭环）
│  ├─ baseline_merging_benchmark.md  ← 主流模型合并基准对标数据报告
│  ├─ generate_assets_and_docx.py    ← 矢量图绘制与 Word 生成器
│  ├─ images/                         ← 论文 300 DPI 高清插图
│  └─ submission_pack/                ← 标准 LaTeX 双盲投稿包（main.tex / references.bib）
│
├─ architecture.md     ← 【系统与架构】
│  └─ 包含 §0 论文架构映射、DSH 适配器、数据流、上下文裁剪与运行时方案 Z 详解
│
├─ training.md         ← 【后训练与实验】
│  └─ 包含 §0 论文训练演进、抗记忆化规程、反事实数据清洗与 9B/27B 双线训练记录
│
├─ operations.md       ← 【运维与切换】
│  └─ 本地双模型（9B llama.cpp / 27B NInfer）运行时管理、显存调优与三档切换指南
│
├─ plans.md            ← 【工程计划】
│  └─ 涵盖 9B OxCoder 与 27B KittyRev 双线训练与部署历史执行记录
│
└─ v6-rebuild.md       ← 【特定模型重建手册】
   └─ 针对 v6 模型的重建路线、权重校验与量化指南
```

---

## 2. 研发体系与学术成果的对应关系

| 本地工程模块 | 对应技术实现 | 升华为学术成果（DSDA 论文） |
|---|---|---|
| **动态外挂切换 (Scheme Z)** | `plugins/dsh-local-ai/` 运行时根据工具/代码意图动态切 LoRA | **定理 1 低秩子空间正交投影推论**：证明参数隔离下任务干涉能量恒等于 0 ($\mathcal{I} \equiv 0$)，优于 Task Arithmetic 与 TIES-Merging |
| **候选工具裁剪 (8~12 簇)** | 适配器层动态注入当前意图簇的难负例工具 | **Candidate-Aware Hard-Negative Clustering**：消除上下文稀释，使工具调用准确率由 75.0% 提升至 82.5% |
| **安全双状态门控** | `train/lines/9b-oxcoder/data/nsfw-gated/` 成对等长样本 | **结构因果模型 (SCM) 反事实门控**：利用 Pearl $do$-算子切断长度混杂因子的后门路径，彻底杜绝虚假长度偏置 |
| **双模型部署体系** | 9B 端侧混合注意力 + 27B 服务端全密集注意力 | **跨架构与跨规模泛化验证**：证明 DSDA 发现的病理机制在不同规模模型上具有普遍性 |

---

## 3. 快速查阅推荐

- **准备论文投稿或导师汇报**：请查阅 [`docs/paper/README.md`](paper/README.md) 与 [`docs/paper/PAPER-AUDIT-REPORT.md`](paper/PAPER-AUDIT-REPORT.md)；
- **了解代码实现与适配器原理**：请查阅 [`docs/architecture.md`](architecture.md)；
- **了解训练样本构造与评测规程**：请查阅 [`docs/training.md`](training.md)；
- **一键复现全部实验指标**：请查阅根目录 [`REPRODUCE.md`](../REPRODUCE.md)。
