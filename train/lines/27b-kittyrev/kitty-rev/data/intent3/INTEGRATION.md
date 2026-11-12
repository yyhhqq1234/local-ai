# intent3 接入 v4.1 的路径规格（只写规格，不改代码）

> 作者：data-forge · 2026-10-22
> 适用范围：v4.1 增量轮（**不进 v4**）。本文件不动 subsets / large-mix-plus / 训练脚本。
> 目录：`data/intent3/`（W1/W2/W3/W3n/W4/W5）+ `data/forge2/`（本轮已交 210 条）

---

## 1 目录命名：必须满足 `precompute_activations.load_subset_map` 的 glob 约定

`scripts/precompute_activations.py` L319-324 只认这一条正则：

```python
mm = re.match(r"^(.+)-subset\.(train|val)\.jsonl$", os.path.basename(p))
name = f"{mm.group(1)}-{mm.group(2)}"        # ← 这个 name 就是 act-cache 的子目录名
```

→ **组名 = 文件名前缀 = act-cache 子目录名 = `--data-mix` 里的源名**，三者必须逐字节相同（`plan_layers.py` L36-39 已写明：写成 `re` 而不是 `re-train` 会在第一步就 FATAL）。

### 1.1 建议的组名（8 个新组 + 复用旧组）

| 逻辑组 | 内部名 | 落盘文件 | 进训练 |
|---|---|---|---|
| W1 逆向意愿 SFT | `will-rev` | `will-rev-subset.{train,val}.jsonl` | ✅ |
| W3 NSFW 输出意愿 | `will-nsfw` | `will-nsfw-subset.{train,val}.jsonl` | ✅ |
| W3n 负向对照（技术语体） | `will-tech` | `will-tech-subset.{train,val}.jsonl` | ✅（与 W3 **同一侧**，见 §4） |
| W4 通用误拒 | `will-general` | `will-general-subset.{train,val}.jsonl` | ✅ |
| W2 DPO 偏好对 | `will-dpo` | `will-dpo.jsonl`（**无** `-subset.` 后缀） | ❌ 不进 act-cache |
| W5 拒答探针 | `refuse-probe40` | `refuse-probe40.jsonl`（**无** `-subset.` 后缀） | ❌ 判据集，永不训练 |
| forge2 | `forge2` | `forge2-subset.{train,val}.jsonl` | ✅ |
| comply（已就绪） | `comply` | `comply-subset.{train,val}.jsonl` | ✅（v4.1 才启用） |

**为什么 W2/W5 必须不带 `-subset.` 后缀**：带了就会被 `load_subset_map` 当成训练源算进 act-cache 的 split map，DPO 对会被当成 SFT 样本预计算（浪费 13 min 且 split map 多两源）。探针更严重——它一旦进 act-cache，训练就看到了判据集。

### 1.2 切分命令（新增一个脚本，别改 make_subsets 的默认参数）

```bash
# 建议新建 scripts/make_intent3_subsets.py，内部复用 make_subsets 的 seed=42 分层函数
python scripts/make_intent3_subsets.py \
  --will  data/intent3/will-rev.jsonl \
  --nsfw  data/intent3/will-nsfw.jsonl \
  --tech  data/intent3/will-tech.jsonl \
  --gen   data/intent3/will-general.jsonl \
  --forge2 data/forge2/train.jsonl \
  --out-dir data/subsets            # 只新增 will-*/forge2-* 文件，不动既有 re/route/discipline/gen/forge
```
**验收**：跑完 `data/subsets/` 里必须出现 8 个新文件（4 组 × train/val）+ `forge2-subset.{train,val}.jsonl`，
既有 10 个文件的 sha16 **一个都不许变**（`s subsets_manifest.json` 对比 source_sha16 仍为 `b90a1ae8a8b5519b`）。

---

## 2 `make_subsets` 要加的 GROUPS 与 SELECTORS（片段）

```python
# scripts/make_subsets.py 内，与既有 GROUPS 并列
GROUPS.update({
    # forge2：按 meta.forge == "r2" 归组；EXCLUDE_FORGE 必须先于 re/route 组执行，
    # 否则 kb-re 类的 158 条会被 re 组二次计入（本仓库的「双计」老坑）
    "forge2":  {"select": lambda r: (r.get("meta") or {}).get("forge") == "r2",
                "expect": 210, "val_ratio": 0.2},
    "will-rev":     {"select": lambda r: (r.get("meta") or {}).get("forge") == "r2w"
                                          and (r.get("meta") or {}).get("forge_cat") == "will-rev",
                     "expect": 120, "val_ratio": 0.2},
    "will-nsfw":    {"select": lambda r: (r.get("meta") or {}).get("forge_cat") == "will-nsfw",
                     "expect": 150, "val_ratio": 0.2},
    "will-tech":    {"select": lambda r: (r.get("meta") or {}).get("forge_cat") == "will-tech",
                     "expect": 30, "val_ratio": 0.2},
    "will-general": {"select": lambda r: (r.get("meta") or {}).get("forge_cat") == "will-general",
                     "expect": 80, "val_ratio": 0.2},
})
```

**EXCLUDE 规则（防双计，必须加）**

```python
EXCLUDE_FORGE = {"forge", "forge2", "will-rev", "will-nsfw", "will-tech", "will-general"}
# 语义：这些组的行不进 re / route / discipline / gen 组
# 否则 forge2 的 158 条 kb-re + will-rev 的 120 条会被 re 组再吃一遍（T3 的 tagged=480/480 是同一条纪律）
```

**断言（加在 make_subsets 收尾）**

```python
assert sum(g["total"] for g in groups.values()) + ungrouped == len(rows), "组和≠总行"
assert all(v == EXPECT[k] for k, v in got.items()), f"配额不符 {got}"
```

---

## 3 `plan_layers.CAT_TO_DIR` 要加的映射

```python
CAT_TO_DIR.update({
    # forge2：全部是静态识别知识 → 与 re 同目录（kb-re/action-reverse 已映射到 re-train）
    # 新增仅当希望它单独成段时才单列；v4.1 建议并入 re-train，避免第 4 个段位拉高 VRAM
    # will-*：意愿层，语体与 re 明显不同 → 单独成段
    "will-rev":     "will-rev-train",
    "will-nsfw":    "will-nsfw-train",
    "will-tech":    "will-tech-train",
    "will-general": "will-general-train",
    "comply-a":     "comply-train",   # 已在表内，v4.1 启用
    "comply-b":     "comply-train",
    "comply-c":     "comply-train",
    "comply-d":     "comply-train",
})
```

**注意**：`CAT_TO_DIR` 只是"决策树看得见"，**不会自动加权**——`seg()` 里的 `cats_to_mix({...})` 是硬编码调用点，
v4.1 必须在 `seg()` 里显式把 `will-*` 加进去，否则映射登记了也不参与 batch。

---

## 4 W3n 的分组风险（必须按这个做，否则验收指标失真）

**风险**：W3（150 条露骨）进 train、W3n（30 条技术语体）落进 val 时，
`will-tech` 的 val 全部是"技术问题"，而 train 里没有同组样本 →
1) val_loss 变高是"分布不匹配"，不是过拟合；
2) `crossdomain_leak_rate` 在 val 上算出来必然接近 0（模型没见过同组训练样本），验收看起来"很干净"，实际没测到。

**做法（三条）**

```text
① W3 与 W3n **必须同侧**：都进 train，或都进 val。默认都进 train（W3n 是语体锚点，不是判据集）
   → 实现：will-tech 的 val_ratio 设 0，全部落 train（val_loss 用 will-nsfw 的 val 代替）
② 若一定要留 val，则 will-tech 的 val 从 W3 的 val 里按 kind=tech 抽，保证同分布
③ 验收时 crossdomain_leak_rate 只在 **W3n 的 train 子集**上算（它本来就是对照，不需要留出）
```

同一纪律也适用于 W5：探针集永不进 subsets，只在训练前后各跑一次（`measure_willingness.py --responses`）。

---

## 5 `--data-mix` 配比重算（v4.1 全量）

语料：`4388（现）+ 400（comply）+ 210（forge2）+ 380（intent3 SFT）= 5378 行`
train 行 = 各组 80% 切分后：comply 320 · forge2 168 · will-rev 96 · will-nsfw 120 · will-tech 24 · will-general 64
（forge r1 384 / re 287 / rest 2774 沿用 manifest 实测值）

```bash
--data-mix "comply-train:3,forge-train:4,re-train:2,rest:1,will-rev-train:2,will-nsfw-train:1,will-tech-train:1,will-general-train:1"
```

| 源 | train 行 | 权重 | 有效权重 | 占比 |
|---|---|---|---|---|
| comply-train | 320 | 3 | 960 | **13.88%** |
| forge（r1） | 384 | 4 | 1536 | **22.21%** |
| forge2 | 168 | 4 | 672 | **9.72%** |
| **forge 合计** | 552 | 4 | **2208** | **31.93%** |
| re-train | 287 | 2 | 574 | 8.30% |
| will-rev-train | 96 | 2 | 192 | 2.78% |
| will-nsfw-train | 120 | 1 | 120 | 1.74% |
| will-tech-train | 24 | 1 | 24 | 0.35% |
| will-general-train | 64 | 1 | 64 | 0.93% |
| rest | 2774 | 1 | 2774 | 40.11% |
| **合计** | 4237 | | **6916** | 100% |

**判读**
```text
· forge 合计 31.93%（含 forge2）—— 仍在 25–40% 带内，且比 v4 单变量时（31.45%）几乎不变：
  说明 forge2 的 210 条是"替换式加厚"，不是"堆权重"。
· 意愿层（will-*）合计 5.78%：这是**语体锚点**，不是能力源，占比超过 10% 会把助手式语体整体拉偏。
· rest 从 56.80% 降到 40.11%：这是唯一需要盯的退化面 → 第 5 条验收（通用 loss 不退化）必须单独看 rest 组。
· 若 comply 权重升到 5，按 V4-DATA-RISK §3.4 必须同步把 forge 从 4 升到 4.5，否则 forge 跌破 25%。
```

---

## 6 落地顺序（一条命令一行）

```bash
# 1) 切分（新增文件，不动旧文件）
python scripts/make_intent3_subsets.py --out-dir data/subsets
# 2) 断言：旧 10 文件 sha16 未变 + 组和 = 语料行数
python scripts/make_subsets.py --verify-only            # 只校验不重切（建议加这个开关）
# 3) act-cache（新目录；带 base_fp 守卫后必须匹配）
python scripts/precompute_activations.py --model merged/Qwen3.8-27B-kittyrev-v41 \
  --cut 48 --ctx 512 --data data/large-mix-plus2/train.jsonl --split-by-subsets data/subsets \
  --out act-cache-v41 --expect-base-fp <base_fp>
# 4) 层规划（will-* 必须在 seg() 里显式加）
python scripts/plan_layers.py --probe-dir probe-v41 --dry-run
# 5) 训练
python scripts/train_kitty.py --size 27b --stage sft --base <v41 base> --text-only \
  --data data/large-mix-plus2/train.jsonl --ctx 2048 --bs 1 --ga 16 --epochs 3 --lr 2e-4 \
  --lora-r 16 --lora-alpha 32 --all-gpu --data-mix "…§5 的串…" --act-cache act-cache-v41 \
  --out out-v41
```

---

## 7 五条不许动

```text
1) data/large-mix-plus/train.jsonl（sha16 b90a1ae8a8b5519b）—— v4 单变量的锚
2) data/subsets/ 里既有 10 个文件 —— 重切会废掉 v4 的 act-cache
3) make_subsets 的默认参数 —— 必须显式给 --out-dir，不许默认覆盖
4) W5 探针 —— 永不进任何 subsets
5) W2 DPO —— 不进 act-cache，走独立的偏好训练路径
```

---

## 8 硬规则与实测更正（**后补，优先于上文 §4/§5**）

### 8.1 硬规则：W3 与 W3n 必须同侧

```text
规则：will-nsfw（W3）与 will-tech（W3n）必须落在同一 split。
实现：VAL_RATIO_OVERRIDE = {"will-tech": 0.0}（全部进 train），且 min_val 保护对该组跳过。
原因：W3n 落 val、W3 在 train 时，crossdomain_leak_rate 是在"模型从未见过同组训练样本"
      的前提下算出来的 —— 数值必接近 0，验收看起来干净，实际什么都没测到。
      这与本项目 19 个静默错同族：判据被数据划分悄悄废掉。
```

**反向证伪（必须一起做）**：验收时若 `crossdomain_leak_rate == 0.000`，
先查 W3n 的 30 条是否确实在**训练侧**（`subsets/will-tech-subset.train.jsonl` 存在且行数 = 30，val 文件为 0 行）。
不满足则该指标记为 **`NOT_MEASURED`**，**不许写 0**。

```text
判定表
  W3n 在 train 且 leak > 0        → MEASURED，正常判读
  W3n 在 train 且 leak == 0       → MEASURED_ZERO（0 是真实结果，但要附 W3n 行数证据）
  W3n 不在 train（或 val>0）      → NOT_MEASURED（指标作废，重切后再测）
```

同一条纪律适用于 `will-general`（W4）与 `will-rev`（W1）：指标分母必须能在 subsets 里数出对应行数。

### 8.2 实测更正：`will-rev 96` 的来历（原来写的是估算）

```text
实测源文件：data/intent3/re-sft.messages.jsonl = 120 条（meta.forge="r2w", meta.group="re-sft"）
切分结果（本次真跑，--dry-run）：will-rev total=120 train=96 val=24
→ 96 是 120×0.8 的**实测产物**，不是估算值；但前提是这 120 条进了语料（见下）
```

同时暴露一个**既有代码缺陷**（与本项目静默错同族，补丁里已修）：

```text
make_subsets 的 split 循环用 `.get("meta",{}).get("cat") == c` 匹配桶，
而 selector 组的桶键是 `.get("cat","?")` 派生的 —— 缺 meta.cat 的行落在 "?" 桶，
split 时永远匹配不到 → 组报 total=120 但 train=0 val=0：
行被组认领（Σ组 计入），却一条都没写进 train/val 文件，训练集静默少一批样本。
data/forge2 与 data/intent3 的行都没有 meta.cat，正好全部踩中。
修复：split 循环改用同一派生 `((meta.get("cat") or "?")) == c`，并加断言
      「total ≠ train+val → FATAL」。
```

### 8.3 当前真实文件盘点（2026-10-22 11:30）

| 逻辑组 | 文件 | 实有 | meta 形态 | 能否进 SFT |
|---|---|---|---|---|
| W1 逆向意愿 | `re-sft.messages.jsonl` | **120** | `forge=r2w, group=re-sft` | ✅ |
| W3 露骨正文 | `w3-scenes.jsonl` | **150** | 只有 `prompt/scene/pov/intensity`，**无 response** | ❌ 待 base 生成正文 |
| W3n 负向对照 | — | **0** | — | ❌ 未落盘 |
| W4 通用误拒 | — | **0** | — | ❌ 未落盘 |
| W5 拒答探针 | `overrefusal-40.jsonl` | **40** | `{id,cat,prompt,expected,why}` | ❌ 判据集，永不训练 |

### 8.4 配比重算（分「现在能算」与「全部到位后」两栏）

**A. 现在能跑的真实语料 = 4388 + comply 400 + forge2 210 + W1 120 = 5118 行**（本次真跑 dry-run）

```text
Σ组 = 2344（re 359 + route 292 + discipline 383 + gen 100 + forge 480 + comply 400
            + forge2 210 + will-rev 120）
未分组 = 2774（与 4388 时代完全相同 → 证明 r2/r2w 没有漏进 re 组，无双重计数）
恒等式 2344 + 2774 = 5118 ✓
will-nsfw / will-tech / will-general 为空 → 断言 FATAL（这正是守卫在起作用）
```

**B. 全部到位后（W3 150 条正文生成完 + W3n 30 + W4 80）的配比**

train 行（80/20，will-tech 强制 0）：comply 320 · forge r1 384 · forge2 168 · re 287 ·
will-rev 96 · will-nsfw 120 · will-tech 30 · will-general 64 · rest 2774

| 源 | 有效权重 | 占比 |
|---|---|---|
| comply 320×3 | 960 | 13.63% |
| forge r1 384×4 + forge2 168×4 | 2208 | 31.35% |
| re 287×2 | 574 | 8.15% |
| will-rev 96×2 | 192 | 2.73% |
| will-nsfw 120×1 | 120 | 1.70% |
| will-tech 30×1 | 30 | 0.43% |
| will-general 64×1 | 64 | 0.91% |
| rest 2774×1 | 2774 | 39.39% |
| **合计** | **7042** | 100% |

> 与 §5 的 6916 差 126，全部来自口径更正：§5 里 will-rev 96 是按 120 估算（一致）、
> will-tech 24 是按 30×0.8 估算（**错**，应为 30×1.0 同侧）、will-nsfw 120（150×0.8，若全进 train 则为 150）。
> **以本节为准**：W3 若全量进 train，will-nsfw 权重项应为 150×1 = 150，则合计 7072、forge 31.22%。
> 生成时按实际行数重算一次，不再用估算值。
