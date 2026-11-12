import io
import sys

sys.stdout.reconfigure(encoding="utf-8")

P = "PLAN-OXCODER-POSTTRAIN.md"
s = io.open(P, encoding="utf-8").read()

START = "## 5 P2 主训练（三阶段，顺序不可换）"
END = "## 6 P3 merge + 冒烟"

i = s.index(START)
j = s.index(END)

NEW = """## 5 P2 主训练（四阶段，2026-10-28 全量实测后重写）

> **本节的参数全部来自实测，覆盖 2026-10-27 的估算版本。**
> 旧版结论（ctx 8192 需 200s/步、ga=16 可用、2A 需 11-14h）已被推翻，原因见 §5.0。

### 5.0 通用配置（每个阶段都必须带，缺一项就出问题）

```bash
# 环境变量（两个都必须）
PYTORCH_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.80
VRAM_FRAC=0.93

# 命令行必带
--ga 4              # ★ 绝不用 16：实测 ga=16 必卡死在第 1 步之后
--optim adamw_torch # paged_adamw_8bit 在 Windows 上同样会卡
--use-liger-ce      # 省 logits（ctx 4096 时省 2 GiB，ctx 9216 时省 4.58 GiB）
--save-total-limit 8
-u                  # Python 不缓冲，否则日志几十/上百分不更新
```

**训练脚本已内置的 4 项修复（不要回退）**：

| # | 修复 | 作用 |
|---|---|---|
| 1 | 全量 fp32 → bf16（179+ 个参数，不只大表） | forward **6.616 → 1.144 s（5.8×）** |
| 2 | 卸载视觉塔 `model.model.visual = None` | 省 0.23 GiB |
| 3 | `set_per_process_memory_fraction(VRAM_FRAC)` | 防 WDDM 换页拖垮系统 |
| 4 | 训练前 `reset_peak_memory_stats()` | peak 不被加载峰值污染 |

**数据必须按长度分桶**（`train/lines/_shared/scripts/bucket_by_length.py`），否则第 48 步起碎片累积、掉速 30 倍。

**实测速度基准**：

| 样本长度 | 单样本时间 | 来源 |
|---|---|---|
| 270 token（kitty 均值） | **0.72 s** | RE 阶段 1401 步实测 |
| 1590 token（2A 均值） | **≈4.3 s** | 按 2.7 ms/token 推算 |
| 4096 token（满 ctx） | **47 s** | hidden-only 基准 |

**ctx 决策**：**统一 4096**（不是旧版说的 2048/8192）。
- ctx 4096 是 12 GB 卡的硬上限（8192 时 reserved 25.98 GiB 超物理 → WDDM 换页 → 1149 s/步；9216 直接 OOM）
- kitty / NSFW 数据 p99 远低于 4096，用 2048 更快，可单独下调

---

### 5.1 RE 阶段 — kitty 工具编排（**已完成 2026-10-28**）

```powershell
train\\.venv\\Scripts\\python.exe -u train\\scripts\\train_qlora9b.py `
  --base train\\models\\OxCoder-9B `
  --data train\\data\\kitty-reverse\\kitty-core-bucketed.jsonl `
  --stage re --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 200 --save-total-limit 8 `
  --out train\\out\\re-stage1-fixed
```

| 项 | 实测结果 |
|---|---|
| 数据 | kitty core 5602 条（64 token 桶） |
| 步数 | 1401 / 1401 |
| 耗时 | **3397 s（56.6 分钟）** |
| train_loss | **1.1102**（末步 0.8186） |
| 速度 | 2.13–2.42 s/步，全程无掉速 |
| 显存 | alloc 恒定 7.622 / reserved 9.41 / free 最低 1.024 GiB |
| 产物 | `train/lines/9b-oxcoder/out/re-stage1-fixed/final`（173 MB） |

**验收结论（详见 `train/RE-STAGE1-REPORT.md`）**：
- 真编造工具 **6 → 1**（-83%）
- 三段式结构（工具+理由 / 参数要点 / 判据）逐字学会
- 工具调用格式正确（`action=xxx target=xxx`）

**待改进**：1 epoch 不够充分，建议补 2-4 epoch，loss 目标 < 0.5。

---

### 5.2 2A — 通用编码 agent 轨迹（**21 h**）

> **重要变更**：RE 阶段已单独训过 kitty，本阶段**不再混 kitty**，直接训轨迹，
> 避免重复 16806 条 kitty 浪费 20 小时。

```powershell
train\\.venv\\Scripts\\python.exe -u train\\scripts\\train_qlora9b.py `
  --base train\\out\\re-stage1-fixed\\final `
  --data train\\data\\agent-traj\\traj-all-bucketed.jsonl `
  --stage re --ctx 4096 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 500 --save-total-limit 8 `
  --out train\\out\\2a-traj
```

| 项 | 值 |
|---|---|
| 基座 | RE 阶段的 adapter（续训） |
| 数据 | 17553 段（swe-8k 16651 + deepswe 424 + rebench 478） |
| 步数 | 17553 / 4 ≈ **4388 步** |
| 单样本 | ≈4.3 s（均值 1590 token） |
| **预估耗时** | **21 h** |
| 判据 | loss 平滑下降；产物完整；抽检 10 条轨迹续写格式正确 |

**注意**：数据文件需先合并 + 分桶（见 §5.5 数据准备）。

---

### 5.3 2B — NSFW 生成（**12 h**）

```powershell
train\\.venv\\Scripts\\python.exe -u train\\scripts\\train_qlora9b.py `
  --base train\\out\\2a-traj\\final `
  --data train\\data\\mix-2b-bucketed.jsonl `
  --stage nsfw --ctx 2048 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 300 --save-total-limit 8 `
  --out train\\out\\2b-nsfw
```

| 项 | 值 |
|---|---|
| 基座 | 2A 的 adapter（续训，保 RE 能力） |
| 数据 | 13668 条（p99 1437 token，ctx 2048 够） |
| 步数 | 13668 / 4 ≈ **3417 步** |
| 单样本 | ≈3.2 s（均值 1178 token） |
| **预估耗时** | **12 h** |
| 判据 | loss 下降；抽检 20 条生成，词表命中率 ≥ 60% |

**lora 用 r=16 / α=32**（`--stage nsfw` 预设），NSFW 是分布注入，秩可低。

---

### 5.4 2C — 长上下文扩展（**30 h**）

```powershell
train\\.venv\\Scripts\\python.exe -u train\\scripts\\train_qlora9b.py `
  --base train\\out\\2b-nsfw\\final `
  --data train\\data\\mix-2c-bucketed.jsonl `
  --stage re --ctx 4096 --ga 4 --optim adamw_torch --bs 1 --epochs 1 `
  --use-liger-ce --save-steps 500 --save-total-limit 8 `
  --out train\\out\\2c-longctx
```

| 项 | 值 |
|---|---|
| 数据 | swe-16k 切分版 14280 段（原始 16k 上下文，ctx 4096 下切分） |
| 步数 | 14280 / 4 ≈ **3570 步** |
| 单样本 | ≈7.5 s（均值 2794 token） |
| **预估耗时** | **30 h** |

---

### 5.5 数据准备（一次性，全部已生成）

| 文件 | 行数 | 用途 | 生成命令 |
|---|---|---|---|
| `kitty-reverse/kitty-core-bucketed.jsonl` | 5602 | RE 阶段 | `bucket_by_length.py --bucket 64` |
| `agent-traj/traj-all-bucketed.jsonl` | 17553 | 2A | 先合并 3 份 chunk4096，再 `--bucket 256` |
| `mix-2b-bucketed.jsonl` | 13668 | 2B | `--bucket 128` |
| `mix-2c-bucketed.jsonl` | 14280 | 2C | `--bucket 128` |

**注意**：`mix-2a-bucketed.jsonl`（34359 条，含 kitty×3）是旧方案，**2A 已不用它**。

---

### 5.6 总时间与关键路径

| 阶段 | 状态 | 耗时 |
|---|---|---|
| RE（kitty） | ✅ **已完成** | 0.9 h |
| 2A（轨迹） | ⬜ | 21 h |
| 2B（NSFW） | ⬜ | 12 h |
| 2C（长上下文） | ⬜ | 30 h |
| **剩余合计** | | **63 h ≈ 2.6 天** |

**关键约束**：
1. 四阶段**必须顺序执行**（后一阶段用前一阶段的 adapter 续训）
2. 每阶段结束都要跑一次冒烟（loss 曲线 + 抽检生成）
3. 显存配置错了会在第 48 步左右崩塌，前 1 小时看起来正常——**必须看 mem-trace 的 reserved 是否平台化**

---

"""

s = s[:i] + NEW + s[j:]
io.open(P, "w", encoding="utf-8").write(s)
print("§5 已重写，文件 %d 字节" % len(s))
