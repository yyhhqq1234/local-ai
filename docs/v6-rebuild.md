# v6 重建计划（KittyRev-27B · qwen3.8-27b-kittyrev-v6）

> **背景**：2026-11-12 17:38，`qwen3.8-27b-kittyrev-v6-iq2s-mtp.ninfer`（9.88 GB）
> 在工作区清理中被误删，且无任何备份（`merged/`、`local-pack/` 此前已空）。
> 三个恢复通道全部失效：回收站（Remove-Item 不进）、D: 卷影副本（无）、
> WinFR / TestDisk / DiskGenius（卡死、装不上、扫不到完好候选）。
>
> **结论**：文件不可恢复，但**重建所需的全部材料健在**，可完整复现。

---

## 1 材料清单（已核对存在）

### 1.1 训练数据 · `train/lines/27b-kittyrev/data/versions/`

| 文件 | 行数 | 体积 | 用途 |
|---|---|---|---|
| `gen8-nsfw-kitty.jsonl` | 22,913 | 60.6 MB | **主 SFT 集**（NSFW 门控 + kitty 逆向） |
| `gen8-gate.jsonl` | 10,221 | 39.1 MB | 门控评测集 |
| `gen7-nsfw-kitty.jsonl` | 22,913 | 59.6 MB | 上一代 SFT 集（对照 / 混配） |
| `gen7-text.jsonl` | 22,913 | 71.0 MB | 纯文本能力保持集 |
| `gen3_1p6-nsfw-kitty.jsonl` | 16,783 | 35.0 MB | 更早一代（历史对照） |
| `gen7-cont.jsonl` | 500 | 2.5 MB | 续训集 |
| `kitty-reverse-train-kitty-core.20261027-203028.jsonl` | — | 5.8 MB | kitty 核心契约集 |

所有 `.jsonl` 都有对应 `.sha256`。

### 1.2 训练与量化脚本

| 路径 | 作用 |
|---|---|
| `kitty-rev/scripts/train_kitty.py` | SFT / DPO 入口，超参全在 argparse |
| `kitty-rev/scripts/` 下 63 个脚本 | 数据构造 / 评测 / 层探针 / 合规探针 |
| `quant/gsq_gumbel.py` · `gtq_gumbel_v2.py` | GSQ 量化（Gumbel-Softmax 学码本，论文级） |
| `quant/run_convert_gsq.py` | 模型 → `.ninfer` 转换入口 |
| `quant/calib-gen2v2.txt` | 校准集（2.0 MB） |
| `quant/imatrix-gen2.dat` | imatrix（13.3 MB） |
| `kitty-rev/logs/PLAN-REVIEW.md` | 110 KB，当时的完整计划与超参讨论 |

### 1.3 缺项（必须补齐）

| 项 | 状态 | 补齐方式 |
|---|---|---|
| `Qwen3.8-27B` 基座 | 2026-11-12 已删 | HF 公开可下（约 52 GB） |
| v6 的 SFT adapter | 删除前 `merged/` 已空 | 重跑 SFT 产出 |

---

## 2 四步重建

### 步骤 1 · 基座

```bash
huggingface-cli download Qwen/Qwen3.8-27B \
  --local-dir train/lines/27b-kittyrev/base/Qwen3.8-27B
```

### 步骤 2 · SFT

超参取自 `train_kitty.py` 默认值 + v6 档位（LoRA r16 / alpha32 / lr2e-4 / bs1 / 3 epoch）。

```bash
python train/lines/27b-kittyrev/kitty-rev/scripts/train_kitty.py \
  --size 27b --stage sft \
  --base train/lines/27b-kittyrev/base/Qwen3.8-27B \
  --data train/lines/27b-kittyrev/data/versions/gen8-nsfw-kitty.jsonl \
  --eval-data train/lines/27b-kittyrev/data/versions/gen8-gate.jsonl \
  --out train/lines/27b-kittyrev/out/v6-rebuild \
  --lora-r 16 --lora-alpha 32 --lr 2e-4 --bs 1 --epochs 3 \
  --max-memory "cuda:0=20GiB,cpu=40GiB"
```

硬要求：训练必须挂**专职监控子 agent**（见 `AGENTS.md` §4.5），每 10 分钟报
`step / loss / lr / 步速 / 显存 alloc·reserved / 判定`。

### 步骤 3 · 合并 + GSQ 量化（IQ2_S 路线）

```bash
python train/lines/27b-kittyrev/quant/run_convert_gsq.py \
  --model train/lines/27b-kittyrev/out/v6-rebuild/merged \
  --calib train/lines/27b-kittyrev/quant/calib-gen2v2.txt \
  --imatrix train/lines/27b-kittyrev/quant/imatrix-gen2.dat \
  --out models/27b/qwen3.8-27b-kittyrev-v6-rebuild.ninfer
```

### 步骤 4 · 验收

```bash
# 放进引擎 model 目录后启动（12 GB 卡参数，已实测）
cp models/27b/qwen3.8-27b-kittyrev-v6-rebuild.ninfer \
   engines/ninfer-27b/ninfer-27b-kv-stream-3arch-20261019/model/

python engines/ninfer-27b/start-27b.py
```

四项判据：

| 项 | 阈值 |
|---|---|
| 启动日志 | 出现 `weights ready \| X GiB`，无 `FATAL` |
| decode | ≥ 60 tok/s（Huihui-Swift 同机实测 68.14） |
| MTP | 接受率 ≥ 70%（同机实测 75%） |
| 门控 / kitty / NSFW 创作 | 用 `data/eval/gate3-20261102.jsonl` + `kitty-rev/scripts/compliance_probe.py` 复测，不低于 `docs/plans.md` 记录的 v6 基线 |

---

## 3 预计成本

| 阶段 | 时间 | 硬件 |
|---|---|---|
| 基座下载 | 2–4 h（视带宽） | — |
| SFT | 6–12 h | 云端 GPU（A800 / 5090，40–80 GB 显存） |
| GSQ 量化 | 1–2 h | 同上 |
| 验收 | 0.5 h | 本机 12 GB 卡 |
| **合计** | **10–19 h** | 折算成本与首次训练（¥500）同量级 |

---

## 4 防复发（已生效）

```text
1) 任何 *.ninfer / *.gguf / *.safetensors / 引擎运行时：清理前必须逐项列清单，等操作者逐项点头
2) 删前先回答「有无可比原件或可复现路径」；无副本的成品一律不动
3) 破坏性操作一次只做一类，做完立即报体积与剩余家底
4) 交付成品必须同时保留「可重建路径」记录（本文件即模板）
```

---

## 5 相关文件

- `docs/plans.md` — 两条训练线总计划
- `train/lines/27b-kittyrev/quant/README.md` — GSQ 量化原理与实测增益
- `train/lines/27b-kittyrev/kitty-rev/logs/PLAN-REVIEW.md` — 当时的完整计划
- `TASKPOINT.md` §2026-11-12 23:05 — 事故记录与材料盘点
