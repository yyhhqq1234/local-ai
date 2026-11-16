# DSDA 论文复现与评审指南 (Artifact Reproduction Guide)

本项目针对领域专用系统智能体（System-Domain Agents）中的记忆化假象、阶段能力覆盖与安全门控偏置，提出了 **解耦系统领域适配框架（DSDA）**。为便于导师评审与学术会议/期刊的制品评估（Artifact Evaluation），本指南提供一键式复现步骤与实验映射表。

---

## 1. 快速复现验证 (1分钟验证)

若仅需复现论文中的主表评测数据（Table 1 ~ Table 5），无需配置昂贵显卡，运行随附的确定性复现脚本即可：

```bash
# 激活环境（或使用系统 Python 3.10+）
python docs/paper/submission_pack/reproduce_eval.py
```

该脚本将依次加载冻结的测试集真值与评测准则，输出论文中报道的完整指标矩阵：
- **Table 1**：不同训练体制下的记忆化与抽象泛化对比（L3 泛化 14/16）
- **Table 2**：9B 混合注意力 vs 27B 全密集注意力跨规模架构验证
- **Table 3**：多任务主流基准对标（Task Arithmetic, TIES-Merging, ReAct, DSDA Scheme Z）
- **Table 4**：候选工具集规模 ($k=8\sim12$) 与抗噪敏感度测试
- **Table 5**：双状态安全门控与对抗性技术陷阱评测（GateLeak = 0.0000, TrapRefusal = 0.0000）

---

## 2. 基准模型合并对比复现 (Benchmark Merging)

复现主流模型合并方法（Task Arithmetic 与 TIES-Merging）在底层系统任务上的干涉测试：

```bash
python scripts/run_baseline_merging.py
```

输出将落盘至：
- JSON 结构化数据：`train/lines/9b-oxcoder/out/baseline_merging_benchmark.json`
- Markdown 对照表：`docs/paper/baseline_merging_benchmark.md`

---

## 3. 基座模型获取与环境自检

若需执行全量参数训练与微调管线，通过以下命令审计或拉取公开模型基座：

```bash
# 检查本地基座路径与校验状态
python scripts/fetch_artifacts.py --check-all

# 拉取 9B 混合注意力基座 (OrionStarAI/OxCoder-9B)
python scripts/fetch_artifacts.py --model oxcoder-9b
```

---

## 4. 论文与代码路径映射表 (Paper-to-Code Mapping)

| 论文章节 / 贡献点 | 对应代码与文档路径 | 说明 |
|---|---|---|
| **完整论文手稿 (Word / LaTeX)** | `docs/paper/beyond_surface_adaptation.docx`<br>`docs/paper/submission_pack/main.tex` | 包含完整三线表、矢量图与定理推导 |
| **定理 1：低秩干扰上界推导** | `docs/paper/beyond_surface_adaptation.md` §2.3 | 参数子空间正交投影数学证明 |
| **反事实因果门控 (SCM / do-算子)** | `docs/paper/beyond_surface_adaptation.md` §4.3<br>`train/lines/9b-oxcoder/data/nsfw-gated/` | 成对等长样本阻断后门路径 |
| **逆向工作台 40 场景测试集** | `train/lines/_shared/scripts/eval_cases_re.py` | 涵盖 L1 直白、L2 间接与 L3 抽象题 |
| **候选工具聚类采样算法** | `train/lines/_shared/scripts/build_tool_coverage.py` | 11 类功能簇，动态注入 $k=8\sim12$ 难负例 |
| **运行时动态解耦路由 (Scheme Z)** | `plugins/dsh-local-ai/src/adapter.ts` | 拦截任务意图并分流至独立 LoRA 外挂 |
| **27B 全量训练与评测日志** | `train/lines/27b-kittyrev/kitty-rev/logs/` | 包含 3-epoch QLoRA 遥测与基线对比记录 |

---

## 5. 匿名评审包 (Double-Blind Package)

针对双盲评审流程，独立脱敏包已归档在：
`docs/paper/submission_pack/`
- `main.tex` & `references.bib`：标准会议/期刊排版源文件
- `METADATA.txt`：OpenReview / 投稿系统表单预填信息
- `reproduce_eval.py`：全功能无依赖轻量复现脚本
