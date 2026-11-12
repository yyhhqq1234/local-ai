# train/ · 训练线根目录（已结项归档）

> **状态：2026-11-12 结项**。两条训练线（9B OxCoder / 27B KittyRev）的训练流程已完成，
> 权重成品已导出为 GGUF / .ninfer 并在本机部署。本目录保留**全部训练数据、脚本与量化实现**，
> 供复现、审计与后续重训。

---

## ⚠️ 内容警告

本目录的训练数据包含 **NSFW / 成人向语料**（`nsfw-gated/`、`gen7/gen8-nsfw-kitty` 等），
用于训练"按显式授权开关决定是否放行"的门控能力。这些内容：

- 仅用于模型能力研究与对齐实验
- 包含成人性描写、露骨词汇与角色扮演文本
- 若你所在地区或平台不允许此类内容，请勿下载或使用

---

## 目录

| 路径 | 内容 |
|---|---|
| `lines/9b-oxcoder/` | 9B 线（Qwen3.5-9B → KittyRev-OxCoder-9B） |
| `lines/27b-kittyrev/` | 27B 线（Qwen3.8-27B → KittyRev-27B GEN3） |
| `lines/_shared/` | 两条线共享的原始语料与脚本 |
| `.venv/` | 训练 Python 环境（不入库） |

## 保留的方法论文档

| 文件 | 作用 |
|---|---|
| `README.md` | 本文件 |
| `PITFALLS.md` | 66 条训练坑清单 + 开训自检 |
| `EVAL-PROTOCOL.md` | 评测规程（判据 / 缓存 / 防卡顿） |
| `PREFLIGHT.md` | 开工前环境检查单 |
| `ANTI-MEMORIZATION.md` | 抗记忆化方案（数据 / 训练 / 评测三层） |
| `TRAINING-LINEAGE.md` | 训练血缘（哪一版用什么数据、什么超参） |

## 数据清单

### 9B 线 · `lines/9b-oxcoder/data/`

| 子目录 | 内容 |
|---|---|
| `kitty-reverse/` | kitty 逆向工具编排语料（工具名 / 参数 / 协议） |
| `agent-traj/` | 2A 轨迹语料（含 Nemotron-SWE 派生的 8k/16k 切片） |
| `nsfw-gated/` | 2B 成对门控集：同请求「开 / 关」两版，用于学开关 |
| `eval/` | 固定评测集（val 85 / test 129） |
| `_legacy/` | 早期混配数据（已被 v6/v8 取代，留作对照） |

### 27B 线 · `lines/27b-kittyrev/data/versions/`

| 文件 | 行数 | 用途 |
|---|---|---|
| `gen8-nsfw-kitty.jsonl` | 22,913 | 主 SFT 集 |
| `gen8-gate.jsonl` | 10,221 | 门控评测集 |
| `gen7-nsfw-kitty.jsonl` | 22,913 | 上一代 SFT 集 |
| `gen7-text.jsonl` | 22,913 | 纯文本能力保持集 |
| `gen3_1p6-nsfw-kitty.jsonl` | 16,783 | 早期版本（对照） |
| `gen7-cont.jsonl` | 500 | 续训集 |

每个 `.jsonl` 均带 `.sha256`。

### 共享 · `lines/_shared/data/`

NSFW 源语料（lexicon / glossary / triage 规则）与原始未切分轨迹。

## 大文件分片说明

GitHub 单文件上限 100 MB。超过 90 MB 的 `jsonl` 已按行边界切分为
`<name>.part01.jsonl` / `.part02.jsonl` …，按序 `cat` 即可还原：

```bash
cat traj-all.part01.jsonl traj-all.part02.jsonl traj-all.part03.jsonl > traj-all.jsonl
```

## 复现入口

```bash
# 9B 线
python lines/9b-oxcoder/tools/...            # 数据构造
python lines/9b-oxcoder/z_train.py ...       # SFT

# 27B 线（详见 docs/v6-rebuild.md）
python lines/27b-kittyrev/kitty-rev/scripts/train_kitty.py --size 27b --stage sft ...
python lines/27b-kittyrev/quant/run_convert_gsq.py ...
```

## 已清理（2026-11-12 结项）

过程日志与旧版结论报告已全部删除，不再保留归档：
- `lines/27b-kittyrev/kitty-rev/logs/v4|v5|v6|v7/` 逐轮日志
- `lines/27b-kittyrev/kitty-rev/logs/*.md` 过程交接与自测记录
- `logs/*.log|*.json` 训练 / 评测 / 监控日志（417 个）
- 根目录旧版结论报告（GEN4 / mix-v5 / R3 / 2A-ACCEPTANCE 等）

保留的只有方法论文档（PITFALLS / EVAL-PROTOCOL / PREFLIGHT / ANTI-MEMORIZATION / TRAINING-LINEAGE）
与可复现的数据、脚本、量化实现。
