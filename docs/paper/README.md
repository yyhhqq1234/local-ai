# DSDA 学术论文与制品包索引 (Research Paper & Artifacts)

> **论文作者与项目所有者**: 杨涵钦（yyhhqq1234，2923165556@qq.com）  
> 本目录归档了学术论文 **《Beyond Surface Adaptation: Deconstructing Memorization, Stage Overwriting, and Gating Biases in Domain-Specialized System Agents》** 的完整交付资产，涵盖 Word 定稿、Markdown 完整稿、标准 LaTeX 投稿包、高分辨率论文图表、基线对标数据以及匿名化可复现制品。

---

## 1. 论文核心资产清单

| 文件 / 目录 | 格式 / 形态 | 说明 |
|---|---|---|
| [`beyond_surface_adaptation.docx`](beyond_surface_adaptation.docx) | Word 格式 (658 KB) | **投稿定稿**：包含 IEEE/ACM 规范排版、三线表、矢量图与代码 Listing 终端渲染 |
| [`beyond_surface_adaptation.md`](beyond_surface_adaptation.md) | Markdown | 论文全量英文文本（包含全部数学推导、定理、数据表与 17 篇参考文献） |
| [`PAPER-FRAMEWORK.md`](PAPER-FRAMEWORK.md) | Markdown | **论文结构框架设计**：五步逻辑主线（背景问题 $\to$ 现有缺陷 $\to$ 提出方法 $\to$ 实验结论 $\to$ 核心价值）、7 章节详细规划与图表清单 |
| [`PAPER-AUDIT-REPORT.md`](PAPER-AUDIT-REPORT.md) | Markdown | **漏洞审查与修复验收报告**：针对 5 大漏洞在本项目中的实证真伪判定、修复举措与验收证明 |
| [`baseline_merging_benchmark.md`](baseline_merging_benchmark.md) | Markdown | **基线对标报告**：Task Arithmetic 与 TIES-Merging 模型合并在底层系统任务上的实测数据 |
| [`generate_assets_and_docx.py`](generate_assets_and_docx.py) | Python 脚本 | 自动化图表绘制（300 DPI）与高保真 Word 论文生成器 |
| [`images/`](images/) | 目录 (PNG) | 论文高清插图（图 1~3）与暗黑终端代码图（Listing 1~3） |
| [`submission_pack/`](submission_pack/) | 目录 | **独立双盲投稿包**：包含 `main.tex`、`references.bib`、`METADATA.txt` 及离线复现代码 |

---

## 2. 论文核心贡献与实验矩阵对照

针对领域专用智能体（Domain-Specialized System Agents）在微调中的三大病理，论文提出了 **DSDA (Decoupled System-Domain Adaptation)** 框架：

```text
┌───────────────────────────────┬───────────────────────────────┬───────────────────────────────┐
│     发现的深层病理缺陷         │        DSDA 提出的解耦方法    │        论文关键实验与表项     │
├───────────────────────────────┼───────────────────────────────┼───────────────────────────────┤
│ 1. 记忆化假象 (Memorization)  │ 4 轴语义扰动扩展 (K=4)        │ Table 1: 记忆化降至 0.210     │
│    (20-Gram 重合度暴涨至 0.515)│ + L1~L3 逐级抽象基准评测      │ (L3 抽象题达 14/16, 87.5%)    │
├───────────────────────────────┼───────────────────────────────┼───────────────────────────────┤
│ 2. 阶段性能力覆盖 (Overwriting)│ 定理 1 低秩子空间正交投影     │ Table 3: 优于 Task Arithmetic │
│    (多阶段微调准确率跌至 10.0%)│ + 动态外挂解耦 (Scheme Z)     │ 与 TIES-Merging (保持 82.5%)  │
├───────────────────────────────┼───────────────────────────────┼───────────────────────────────┤
│ 3. 虚假长度捷径 (Length Bias) │ 结构因果模型 (SCM) 反事实建模 │ Table 5: GateLeak = 0.0000    │
│    (正负样本 8.4x 长度差异)   │ + 等长配对训练 (切断后门路径) │ TrapRefusal = 0.0000          │
├───────────────────────────────┼───────────────────────────────┼───────────────────────────────┤
│ 4. 架构与规模泛化性           │ 跨混合注意力和全自注意力      │ Table 2: 9B (OxCoder) 与      │
│    (避免单模型单一任务质疑)   │ 跨规模 (9B 与 27B) 完整验证   │ 27B (Qwen) 双架构实测通过     │
└───────────────────────────────┴───────────────────────────────┴───────────────────────────────┘
```

---

## 3. 快速复现指引 (Artifact Reproduction)

对于审稿人或导师，可直接通过根目录的 `REPRODUCE.md` 指引或运行本目录下的轻量脚本：

```bash
# 1. 快速复现论文所有核心表格（Table 1 ~ Table 5）
python docs/paper/submission_pack/reproduce_eval.py

# 2. 现场复算 Task Arithmetic 与 TIES-Merging 模型合并对标数据
python scripts/run_baseline_merging.py

# 3. 重新渲染所有 300 DPI 图表并生成 Word 文档
python docs/paper/generate_assets_and_docx.py
```

---

## 4. 投稿系统表单预填 (Submission Metadata)

双盲投稿所需的标题、简短题目、TL;DR（<250字符）、纯文本格式摘要及学科分类已整备至：
[`submission_pack/METADATA.txt`](submission_pack/METADATA.txt)
可直接复制粘贴至 OpenReview、IEEE Author Portal 或 EasyChair 投稿系统。
