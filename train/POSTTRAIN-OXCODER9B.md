# OxCoder-9B 双能力后训练 → .ninfer 总方案

> 2026-10-26。目标：以工程能力最强的 9B（OxCoder-9B / SWE-bench 73.5）为基座，
> 注入**逆向工程**与**NSFW 生成**两项能力，产出可在本机 NInfer 引擎运行的 `.ninfer`。
> 硬件：RTX 5070 Ti Laptop 12 GB / 32 GB RAM。本文件是执行总纲，细节在各脚本内。

---

## 0 决策表

| 决策点 | 选择 | 理由 |
|---|---|---|
| 基座 | **OxCoder-9B**（`OrionLLM/OxCoder-9B`，Apache-2.0） | SWE-bench 73.5 / T-Bench 49.6，9B 档工程能力天花板；基座为 Qwen3.5-9B，与 nInfer 原生架构同族 |
| 备选基座 | `huihui-ai/Huihui-Qwen3.5-9B-abliterated` | 已无审查，但工程能力只有 53.2，需从 OxCoder 蒸馏，多一跳 |
| **顺序** | **去审查 → SFT → merge → 转 .ninfer** | 见 §2，顺序反了会白干 |
| 去审查手段 | **Heretic**（`_repos/heretic`，TPE 自动搜索） | 同时最小化拒绝数与 KL 散度，9B 上损伤最小；README 明确支持 Qwen3.5 混合架构 |
| 训练方式 | QLoRA 4bit NF4，分段 | 12 GB 实测上限；27B 已证明不可训（`kitty-rev/docs-12gb-feasibility.md`） |
| 交付容器 | `.ninfer` v3 | 本机引擎唯一可加载格式；converter 与 9B recipe 已就位 |

## 1 为什么不是 27B，也不是 abl 版基座

```text
27B   4bit 权重 12.59 GiB > 可用 10.2-10.5 GiB，8 条 offload 路径全部实测失败
      （kitty-rev/docs-12gb-feasibility.md §2，失败点分别是显存 / meta 张量 / 主机内存）
9B    4bit 权重 ≈5.0 GiB + 激活 2.2 GiB + context 0.9 → 8.1 GiB，留 3-4 GiB 余量
      → 这是唯一能开 ctx 2048 且不 offload 的档位
```

不直接用 Huihui-abliterated 的原因：它的 SWE-bench 是 53.2，OxCoder 是 73.5。先 abliterate 再 SFT，两项能力都能保住；反过来要在 53.2 的底座上补 20pp 工程能力，难度大得多。

## 2 顺序为什么必须是「去审查 → SFT」

```text
✓ 正确：基座 ──Heretic──> 无审查底座 ──LoRA(RE+NSFW)──> merge ──convert──> .ninfer
   去审查作用在**残差流方向**上，是全局权重手术；
   SFT 在其后注入能力，LoRA 只教"怎么做"，不再需要对抗拒绝。

✗ 错误：基座 ──LoRA──> merge ──Heretic──> ?
   Heretic 会对合并后的权重做方向消融，刚训进去的 adapter 效果被一并扰动；
   且 Heretic 的 KL 目标以"原模型"为基准，基准已含你的 adapter，等于在
   一个刚被改过的模型上再改一次，双重偏移，不可控。
```

## 3 四阶段执行

```text
阶段 0  基座与元数据                                  [需下载 ~18 GB]
  OxCoder-9B safetensors → train/models/OxCoder-9B
  metadata（config/generation_config/tokenizer*）→ train/models/metadata-oxcoder9b

阶段 1  去审查（Heretic）                              [约 40-90 分钟，12 GB]
  train\scripts\abliterate_9b.ps1
  产出：train/models/OxCoder-9B-abliterated
  门禁：拒绝率显著下降且 KL 可控（脚本打印），**先跑 eval 再进阶段 2**

阶段 2  SFT（两段，见 §4）                              [每段 1-3 小时]
  2a  RE     train\data\mix-re.jsonl     （现有 690 条）
  2b  NSFW   train\data\mix-nsfw.jsonl   （需自备，规格见 §5，含 15% RE 回放）
  产出：train/out/oxcoder9b-re/final、.../nsfw/final

阶段 3  合并 + 转 .ninfer                              [约 20-60 分钟]
  merge.py  → train/merged/oxcoder9b-abl-re-nsfw
  convert   → train/tools/ninfer-convert/convert-oxcoder9b.cmd
  产出：train/models/oxcoder-9b-abl-re-nsfw.ninfer
```

每阶段结束都跑 `kitty-rev/eval/eval_kitty_v6.py`（RE）+ NSFW 抽样人评，**任何一项回退超过阈值就停**。

## 4 训练配方（`train/scripts/train_qlora9b.py` 已内置）

| 段 | ctx | r | alpha | lr | epoch | ga | 目的 |
|---|---|---|---|---|---|---|---|
| re | 2048 | 32 | 64 | 1e-4 | 4 | 16 | 吃下工具语法与决策链（伪代码/回包格式需要容量） |
| nsfw | 2048 | 16 | 32 | 5e-5 | 2 | 16 | 注入分布而不重排权重；低 r 是关键 |
| joint（可选） | 2048 | 24 | 48 | 6e-5 | 3 | 16 | 一次性混训，求稳方案 |

显存预算（9B QLoRA，实测口径推演）：权重 5.0 + 激活 2.2 + context 0.9 ≈ **8.1 GiB / 12.2 GiB**。

两段都做时，第二段的 `--base` 要指向 merge 后的模型（不是原始 abliterated），否则 NSFW adapter 无法叠在第一段上——`.ninfer` 只能装一份权重。

## 5 NSFW 数据规格（硬要求）

```text
量      ≥1500 条（当前 RE 是 690 条，NSFW 少于 1500 会被 RE 淹没）
格式    {"messages":[{"role":"user",...},{"role":"assistant",...}]}  多轮 2-4 轮
长度    每轮 200-600 字
构成    60% 露骨场景        —— 能力本身
        25% 亲密递进/氛围     —— 保文风，防"关键词堆砌"退化
        15% 角色一致性与拒绝边界（成年、双方同意框架）—— 防人格崩坏与越界
禁止    未成年角色、真实人物、非自愿框架 —— 这类样本会同时污染语言质量与可用性
配比    训练时由 build_mix.py 强制混入 15% RE 回放，不许关
```

没有 NSFW 数据也能跑：`--stage re` 单独只训逆向能力，产出纯净的 RE 版 `.ninfer`。

## 6 验收矩阵

| 阶段 | 检查 | 判据 | 工具 |
|---|---|---|---|
| 1 去审查 | 拒绝率 | 目标 prompt 拒绝数显著下降 | heretic 输出 + 人工 20 条抽检 |
| 1 去审查 | 能力保持 | KL 报告值在 heretic 建议范围内 | heretic 输出 |
| 1 去审查 | 工程能力 | SWE 型抽检不低于 73.5 − 3pp | 自带 5 个真实 issue A/B |
| 2a RE | eval_re_extended | 不低于基线 − 1 项 | `kitty-rev/eval/eval_kitty_v6.py` |
| 2b NSFW | RE 回退 | eval_re 不低于 2a 结果 − 2 项 | 同上 |
| 2b NSFW | 生成质量 | 20 条抽检无重复退化/人格崩坏 | 人工 |
| 3 转换 | 引擎加载 | `/v1/models` 200 | `ninfer_model` / curl |
| 3 转换 | 推理 | `finish=stop`，非 error | 一次真实请求 |
| 3 转换 | MTP 组件 | 不报 `missing component mtp` | 引擎日志 |

## 7 已知卡口

1. **MTP 组件**：本机引擎曾报 `Qwen3.5 config: missing component mtp`。9B 若不带 MTP 头可能被拒载，对策见 `train/tools/ninfer-convert/OXCODER9B-NINFER.md` §5。
2. **RE 数据量偏少**：690 条 / 0.36 M 字符。9B r=32 四 epoch 约 0.8 M token 训练量，属下限。建议先扩到 1500-2000 条再进阶段 2a。
3. **两段串联的 adapter 叠加**：`.ninfer` 只吃单一权重，所以第二段必须在 merge 后的模型上训，不能用 `PeftModel.load_adapter` 叠加后直接转。
4. **Heretic 在 9B 上的 KL**：9B 表征余量小于 27B，abliteration 损伤相对更大。若抽检发现 RE 能力明显下滑，回落方案是 `_repos/abliteration`（grimjim 双向投影，可指定层范围，更保守）。

## 8 与现有资产的对应

| 现有资产 | 用途 |
|---|---|
| `train/kitty-rev/data/forge/*.jsonl`（480 条） | RE 训练主料 |
| `train/kitty-rev/data/forge2/train.jsonl`（210 条） | RE 训练补充 |
| `train/kitty-rev/data/eval_re_extended.jsonl`（60 条） | RE 回归评测 |
| `train/scripts/train_qlora.py` | 8b/27b 路径，保持不动 |
| `train/scripts/merge.py` | 阶段 3 合并（需确认支持任意 base 目录） |
| `_repos/heretic` | 阶段 1 去审查 |
| `_repos/abliteration` | 阶段 1 保守回落方案 |
| `train/tools/ninfer-convert/` | 阶段 3 转换（9B recipe 已补） |
