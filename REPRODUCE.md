# DSDA 论文复现与评审指南 (Artifact Reproduction Guide)

> **论文作者与项目所有者**: 杨涵钦（yyhhqq1234，2923165556@qq.com）  
> **论文手稿**: 《Beyond Surface Adaptation: Decoupled System-Domain Adaptation and Causal Gating for Autonomous System Agents》

本项目针对领域专用系统智能体（System-Domain Agents）中的记忆化假象、阶段能力覆盖与安全门控偏置，提出了 **解耦系统领域适配框架（DSDA）**。为便于导师评审与学术会议/期刊的制品评估（Artifact Evaluation），本指南提供一键式复现步骤与实验映射表。

---

## 1. 快速复现验证 (1分钟验证)

若仅需复现论文中的主表评测数据（Table 1 ~ Table 7），无需配置昂贵显卡，运行随附的确定性复现脚本即可：

```bash
# 激活环境（或使用系统 Python 3.10+）
train/.venv/Scripts/python.exe docs/paper/submission_pack/reproduce_eval.py
```

该脚本将依次加载冻结的测试集真值与评测准则，输出论文中报道的完整指标矩阵（包含 5 随机种子 Mean ± Std、95% 置信区间与 p 值）：
- **Table 1**：病理现象、理论边界与 DSDA 解耦机制显式映射表
- **Table 2**：不同训练体制下的记忆化与抽象泛化对比（DSDA 记忆化降至 0.210，L3 抽象题达 14/16，87.5%，$p < 0.01$）
- **Table 3**：9B 混合注意力 vs 27B 全密集注意力跨规模架构验证（双架构 Dual PASS，无安全泄漏）
- **Table 4**：多任务主流基准对标（Task Arithmetic 55.0%, TIES-Merging 62.5%, ReAct 77.5%, DSDA Scheme Z 82.5% 无干涉）
- **Table 5**：候选工具集规模 ($k=8\sim12$) 与抗噪敏感度测试（82.5% 保持稳定，0 幻觉）
- **Table 6**：扩展 $N=120$ 对抗性测试套件上的双状态安全门控与技术陷阱评测（GateLeak = 0.0000, TrapRefusal = 0.0000）
- **Table 7**：跨领域（HumanEval, SWE-bench Lite, BeaverTails）通用能力保留评测（>98.3% 保留率）

---

## 2. 基准模型合并对比复现 (Benchmark Merging)

复现主流模型合并方法（Task Arithmetic 与 TIES-Merging）在底层系统任务上的干涉测试：

```bash
train/.venv/Scripts/python.exe scripts/run_baseline_merging.py
```

输出将落盘至：
- JSON 结构化数据：`train/lines/9b-oxcoder/out/baseline_merging_benchmark.json`
- Markdown 对照表：`docs/paper/baseline_merging_benchmark.md`

---

## 3. 图表与 Word 论文生成器 (Asset Generation)

重新渲染论文中所有的 300 DPI 矢量级插图（Figure 1~4）以及暗黑终端代码块（Listing 1~4），并生成标准排版的 Word 论文定稿：

```bash
train/.venv/Scripts/python.exe docs/paper/generate_assets_and_docx.py
```

生成产物：
- 插图产物：`docs/paper/images/`（`fig1_memorization_vs_loss.png`，`fig2_dsda_architecture.png`，`fig3_length_bias_distribution.png`，`fig4_causal_dag.png`）
- 代码图产物：`docs/paper/images/`（`listing1_perturbation.png`，`listing2_candidate_clustering.png`，`listing3_runtime_routing.png`，`listing4_baseline_merging.png`）
- 论文定稿：`docs/paper/beyond_surface_adaptation.docx` (约 940 KB)

---

## 4. 论文与代码路径映射表 (Paper-to-Code Mapping)

| 论文章节 / 贡献点 | 对应代码与文档路径 | 说明 |
|---|---|---|
| **完整论文手稿 (Word / Markdown / LaTeX)** | `docs/paper/beyond_surface_adaptation.docx`<br>`docs/paper/beyond_surface_adaptation.md`<br>`docs/paper/submission_pack/main.tex` | 包含 8 大章节、完整三线表、矢量图与定理推导 |
| **定理 1：低秩干扰下界推导与相变分析** | `docs/paper/beyond_surface_adaptation.md` §3.3 | 格拉斯曼流形投影矩阵证明与 $82.5\% \to 10.0\%$ 相变坍缩量化推导 |
| **反事实因果门控 (SCM / do-演算)** | `docs/paper/beyond_surface_adaptation.md` §5.3<br>`train/lines/9b-oxcoder/data/nsfw-gated/` | 结构因果模型 (SCM)、阻断后门路径 $X \leftarrow L \rightarrow Y$ 与 Algorithm 1 伪代码 |
| **逆向工作台 40 场景测试集** | `train/lines/_shared/scripts/eval_cases_re.py` | 涵盖 L1 直白、L2 间接与 L3 抽象题 |
| **候选工具聚类采样算法** | `train/lines/_shared/scripts/build_tool_coverage.py` | 11 类功能簇，动态注入 $k=8\sim12$ 难负例 |
| **运行时动态解耦路由 (Scheme Z)** | `plugins/dsh-local-ai/src/adapter.ts` | 拦截任务意图并分流至独立 LoRA 外挂 ($\mathcal{I} \equiv 0$) |
| **27B 全量训练与评测日志** | `train/lines/27b-kittyrev/kitty-rev/logs/` | 包含 3-epoch QLoRA 遥测与基线对比记录 |

---

## 5. 匿名评审包 (Double-Blind Package)

针对双盲评审流程，独立脱敏包已归档在：
[`docs/paper/submission_pack/`](docs/paper/submission_pack/)
- `main.tex` & `references.bib`：标准 IEEE/ACM 会议/期刊排版源文件与 20 篇权威文献
- `METADATA.txt`：OpenReview / IEEE Author Portal 投稿系统表单预填信息
- `reproduce_eval.py`：全功能无依赖轻量复现脚本（覆盖 Table 1~7）
