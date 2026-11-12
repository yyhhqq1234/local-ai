# v4.1 接入清单（D 项 · 最终规格）

> 作者：willing-forge-2 · 2026-10-22
> 状态：**规格，不改任何脚本**。口径裁决 D1–D7 全部按 lead 落定（§1）。
> 表由脚本生成：`tmp/wf2/gen_mix_table.py`（复跑即得，人不手抄百分比）

---

## 1 四条裁决（最终口径，覆盖 INTEGRATION.md 旧文）

| 编号 | 裁决 | 落地方式 | 验收 |
|---|---|---|---|
| **D1** | will-rev **改选择器，不动数据** | selector = `(meta.forge_cat=="will-rev") or (meta.group=="re-sft")` | `make_subsets --dry-run` 里 will-rev total **必须 = 120**（不是 0） |
| **D2** | will-* 每条 **三键全写** `{forge, group, forge_cat}` | 数据侧写法（W3n/W4 已按此落盘） | 两个 selector 各跑一次，选中集合**逐字节相同** |
| **D3** | 权重表 **由脚本生成**，数字必须能从 `wc -l` 复算 | `gen_mix_table.py`（本文件 §3 的表就是它的输出） | Σ组 == 语料总行（脚本内 FATAL 断言） |
| **D4** | **rest 权重 1.2 → 1.6**（lead 2026-10-22 15:2x 批准） | §4；`gen_mix_table.py --rest 1.6` | rest ≥42%（实测 **46.15%**）**且 forge 仍 ≥25%**（实测 **28.70%**） |
| **D5** | **唯一基数 = 语料全量行 × 权重**（lead 15:3x 裁决） | 三处口径冲突（A 基数 / B 基数 / 我的）统一到这唯一基数 | 恒等式 `Σ组 == 语料总行`（脚本内 FATAL 断言）；脚本只有一份实现（`tmp/wf2/` 是转发壳） |
| **D7** | **route/discipline/gen 各给权重 1，进混料**（lead 15:5x） | `--data-mix` 追加 `route-train:1,discipline-train:1,gen-train:1`；脚本默认给 1（`--no-weight-small` 仅作对照） | rest ≥42%（实测 **42.71%**，边距 0.71pp）且 forge ≥25%（实测 **26.56%**）且 Σ组 == 5378 |


D1 的理由（lead）：`re-sft.messages.jsonl` 是既有产物（sha16 已入 manifest），改数据会让隔离结果与 manifest 同时失效；选择器只是读法。
D2 的理由：INTEGRATION 读 `forge_cat`，`plan_layers` 读 `group`；只写一边 = 另一边选 0 行且不报错。
D3 的理由：INTEGRATION §5 用「80% 切分后的 train 行」，rest 用「未分组全量 2774」——两个基数不同，才出现 6916 / 7042 / 7072 三个合计。本清单统一到**语料全量行数**一个基数（F3 已确认子集 val 行 100% 在 train.jsonl 内，切分只是 act-cache 的视图）。

---

## 2 组名 / 条数 / 权重 / act-cache 目录（一表通）

组名 = 文件名前缀 = act-cache 子目录名 = `--data-mix` 源名，**四者逐字节相同**（`precompute_activations.load_subset_map` 的正则只认 `^(.+)-subset\.(train|val)\.jsonl$`）。

| 组名 | 逻辑组 | 落盘文件 | 条数（实测） | 权 重 | act-cache 目录 | 进 act-cache | 进训练 |
|---|---|---|---:|---:|---|---|---|
| `comply` | W1 域合规 | `data/intent2/comply-subset.{train,val}.jsonl` | 400 | 3 | `comply-train` | ✅ | ✅ |
| `forge` | forge r1 | `data/subsets/forge-subset.{train,val}.jsonl` | 480 | 4 | `forge-train` | ✅ | ✅ |
| `forge2` | forge2 | `data/forge2/forge2-subset.{train,val}.jsonl` | 210 | 4 | `forge2-train` | ✅ | ✅ |
| `re` | re 组 | `data/subsets/re-subset.{train,val}.jsonl` | 359 | 2 | `re-train` | ✅ | ✅ |
| `route` | route 组 | `data/subsets/route-subset.{train,val}.jsonl` | 292 | 1 | `route-train` | ✅ | ✅ |
| `discipline` | discipline | `data/subsets/discipline-subset.{train,val}.jsonl` | 383 | 1 | `discipline-train` | ✅ | ✅ |
| `gen` | gen | `data/subsets/gen-subset.{train,val}.jsonl` | 100 | 1 | `gen-train` | ✅ | ✅ |
| `will-rev` | W1 逆向意愿 | `data/intent3/will-rev-subset.{train,val}.jsonl` | **120** | 2 | `will-rev-train` | ✅ | ✅ |
| `will-nsfw` | W3 NSFW 意愿 | `data/intent3/will-nsfw-subset.{train,val}.jsonl` | **W3 实收 n**（目标 150） | 1 | `will-nsfw-train` | ✅ | ✅ |
| `will-tech` | W3n 负向对照 | `data/intent3/will-tech-subset.train.jsonl`（**val 0 行**） | **30** | 1 | `will-tech-train` | ✅ | ✅ |
| `will-general` | W4 通用误拒 | `data/intent3/will-general-subset.{train,val}.jsonl` | **80** | 1 | `will-general-train` | ✅ | ✅ |
| `will-dpo` | W2 DPO 对 | `data/intent3/will-dpo.jsonl`（**无 `-subset.`**） | 100 对 | — | — | ❌ | 走偏好训练 |
| `refuse-probe40` | W5 探针 | `data/intent3/refuse-probe40.jsonl`（**无 `-subset.`**） | 40 | — | — | ❌ | ❌ 永不训练 |

**本组已交（2026-10-22）**
```text
will-tech    30 条  data/intent3/w3n-negative.jsonl   md5 4156c30e（验收见 tmp/wf2/w3n-check.json）
will-general 80 条  data/intent3/w4-general.jsonl    md5 bd072fa4（验收见 tmp/wf2/w4-check.json）
```

---

## 3 权重表（脚本生成 · 唯一基数 = 语料全量行 × 权重）

> **D5 基数裁决（lead 15:3x）**：唯一基数 = **语料全量行 × 权重**，只有它保住恒等式 `Σ组 == 语料总行数`。
> **D7 短板组进混料（lead 15:5x）**：route 292 + discipline 383 + gen 100 **各给权重 1**
> （对着 kitty23 的 tool-route 1/9 短板：tool-route → route-train，discipline → discipline-train）。
>
> 两口径并存，别混用：
>
> | 口径 | 775 行权重 | rest | forge | will-* | 合计有效权重 |
> |---|---:|---:|---:|---:|---:|
> | D5（旧，作废） | 0 | 46.15% | 28.70% | 5.20% | 9616 |
> | **D7（现行）** | **1** | **42.71%** | **26.56%** | **4.81%** | **10391** |
>
> 唯一实现：`train/lines/27b-kittyrev/kitty-rev/tmp/v41/gen_mix_table.py`（`tmp/wf2/` 那份是转发壳）。

### 3.1 现状（W3 未落盘，rest=1.6，D7）

| 组 | 行数 | 权重 | 有效权重 | 占比 |
|---|---:|---:|---:|---:|
| forge | 480 | 4 | 1920 | 18.75% |
| forge2 | 210 | 4 | 840 | 8.20% |
| re | 359 | 2 | 718 | 7.01% |
| comply | 400 | 3 | 1200 | 11.72% |
| **route** | **292** | **1** | **292** | **2.85%** |
| **discipline** | **383** | **1** | **383** | **3.74%** |
| **gen** | **100** | **1** | **100** | **0.98%** |
| will-rev | 120 | 2 | 240 | 2.34% |
| will-tech | 30 | 1 | 30 | 0.29% |
| will-general | 80 | 1 | 80 | 0.78% |
| will-nsfw | 0 | 1 | 0 | 0.00% |
| rest | 2774 | 1.6 | 4438 | **43.34%** |
| **合计** | **5228** | | **10241** | 100% |

### 3.2 投影（W3 实收 150，rest=1.6）——**开跑口径（D4 + D5 + D7）**

| 组 | 行数 | 权重 | 有效权重 | 占比 |
|---|---:|---:|---:|---:|
| comply | 400 | 3 | 1200 | 11.55% |
| forge | 480 | 4 | 1920 | 18.48% |
| forge2 | 210 | 4 | 840 | 8.08% |
| **forge 合计** | **690** | 4 | **2760** | **26.56%** |
| re | 359 | 2 | 718 | 6.91% |
| route | 292 | 1 | 292 | 2.81% |
| discipline | 383 | 1 | 383 | 3.69% |
| gen | 100 | 1 | 100 | 0.96% |
| will-rev | 120 | 2 | 240 | 2.31% |
| will-nsfw | 150 | 1 | 150 | 1.44% |
| will-tech | 30 | 1 | 30 | 0.29% |
| will-general | 80 | 1 | 80 | 0.77% |
| **will-* 合计** | **380** | | **500** | **4.81%** |
| rest | 2774 | 1.6 | 4438 | **42.71%** |
| **合计** | **5378** | | **10391** | 100% |

**判读**
```text
· 三个联动数：rest 42.71% · forge 26.56% · will-* 4.81%（任缺一个算未交付）
· rest 42.71% 只比 42% 线高 0.71pp —— 这是本表最薄的地方（见 §4.3 边距表）
· forge 26.56% 带内但贴下沿（25-40%）；再给任何新源权重，forge 会先破线
· 775 行从"零曝光"变成 7.77% 的有效权重（292+383+100=775），正好打在 tool-route 1/9 的短板上
· **W3 扩量上限被压到 327 行**（D7 分母变大但 rest 分子不变，42% 线来得更早）；
  forge 25% 线要到 799 行才破。→ 想扩 W3，必须同时抬 rest（§4.3 给了每档权重）
```


---

## 4 rest 权重 1.6（D4 批准）· D7 后边距变薄（必须知道）

> **D4（15:2x 批准）**：rest 1.2 → 1.6。理由——"R1 的 1.2 是在『W3 未定』时算的；W3 实收 150 行后分母变了"。
> **D7（15:5x）之后**：775 行短板组进了分母，rest 从 46.15% 回落到 **42.71%**，只比 42% 线高 **0.71pp**。
> 1.6 仍然够用（lead 的"rest 掉破 42% 就抬 rest"条件是"掉破"，不是"变薄"，所以不动）。

| W3 实收 | rest 权重 | rest 占比（D7 口径） | forge | 判读 |
|---:|---:|---:|---:|---|
| 150 | 1.2 | 35.86% | 29.74% | 红停档（<36） |
| 150 | 1.4 | 39.48% | 28.06% | 必须调权重 |
| 150 | 1.5 | 41.14% | 27.29% | 复核 |
| 150 | 1.554 | **42.00%** | 26.89% | 刚好压线（数学解，不推荐当默认） |
| 150 | **1.6** | **42.71%** | **26.56%** | **正常 ✅（现行，边距 0.71pp）** |
| 150 | 1.8 | 45.62% | 25.21% | 正常，但 forge 只剩 0.21pp 余量 |

**原因**：R1 的 1.2 是在 v4 口径（分母 4388）下推的；v4.1 分母涨到 5378，rest 分子没变（2774 行），占比必然掉。这不是数据问题，是分母问题——所以调 rest 权重，不删数据。

### 4.1 联动纪律（lead 写死，违反必出事）

```text
任何一次调权重，报告必须同时给出 rest 与 forge 两个数。
  rest  ↑ → forge ↓（分母被 rest 吃掉）      rest 吃的是占比，不是行数
  forge ↑ → rest ↓                           两个都是"大项"，此消彼长

本轮实测（W3=150，D7 口径）：
  rest 1.2 → rest 35.86%（红停）· forge 29.74%（OK）
  rest 1.6 → rest 42.71%（正常）· forge 26.56%（OK 但贴下沿 1.56pp）
  rest 1.8 → rest 45.62%（正常）· forge 25.21%（OK，只剩 0.21pp —— 这时已经不能再加 rest）

下沿保护：forge 跌破 25% 时，允许的两个动作只有
  ① 把 rest 回退到 1.5（41.14%，落"复核"带 → 需 lead 复核，我不自行决定）
  ② 同时抬 comply 与 forge（3→3.5 / 4→4.5），不许只抬 comply
禁止：靠删 will-* / route / discipline 行把占比凑回去（那是减数据，不是调权重）；
      **尤其禁止降 route/discipline/gen** —— 那 775 行是对着 kitty23 tool-route 1/9 短板的信号。
```

### 4.2 775 行零曝光 → 已由 D7 解决（保留记录）

```text
原状（D5）：route 292 + discipline 383 + gen 100 = 775 行（语料 14.4%）不在 --data-mix 清单里 → 权重 0 → 零曝光。
            它们躺在大混料文件里，wc -l 数得到、"5378 行"也含它们 —— 数字对得上，被数对象不在内。
D7 处置：三组各 1，进 --data-mix（route-train:1,discipline-train:1,gen-train:1）→ 7.77% 有效权重。
         代价：rest 46.15% → 42.71%（-3.44pp）、forge 28.70% → 26.56%（-2.14pp）。两项都仍在合规带内。
```

### 4.3 边距表：W3 扩量时必须同步抬 rest（脚本 --md 同表）

| W3 行数 | rest 1.6 时 rest% | 保持 42% 所需 rest 权重 |
|---:|---:|---:|
| 150（现行） | 42.71% | 1.554 |
| 200 | 42.51% | 1.567 |
| 300 | 42.10% | 1.593 |
| **327** | **42.00%** | **1.600** ← 1.6 的临界点 |
| 400 | 41.71% | 1.619 |
| 600 | 40.94% | 1.671 |
| 800 | 40.20% | 1.724 |

```text
结论：D7 之后 W3 的扩量上限是 **327 行**（再往上 rest 就破 42%，因为分母被 775 行撑大了）。
要扩到 400 行 → rest 抬到 1.62；600 行 → 1.67；800 行 → 1.72。
同步检查 forge：W3 到 799 行时 forge 才破 25%，所以 327-799 这段的约束是 rest，不是 forge。
```




---

## 5 `GROUPS` / `EXCLUDE` 规格（只给规格，不改脚本）

```python
# scripts/make_subsets.py —— 与既有 GROUPS 并列追加（不替换、不改默认参数）
GROUPS.update({
    "forge2": {"select": lambda r: (r.get("meta") or {}).get("forge") == "r2",
               "expect": 210, "val_ratio": 0.2},

    # D1 裁决：双条件选择器（forge_cat 或 group 任一命中）
    "will-rev": {"select": lambda r: ((r.get("meta") or {}).get("forge_cat") == "will-rev"
                                      or (r.get("meta") or {}).get("group") == "re-sft"),
                 "expect": 120, "val_ratio": 0.2},

    # D2 裁决：三个键都写，这里用 forge_cat 作主键；group 作兜底（等价性由断言 G5/H6 保证）
    "will-nsfw":    {"select": lambda r: (r.get("meta") or {}).get("forge_cat") == "will-nsfw",
                     "expect": None,   # = W3 实收 n；不许写死 150
                     "val_ratio": 0.0},
    "will-tech":    {"select": lambda r: (r.get("meta") or {}).get("forge_cat") == "will-tech",
                     "expect": 30, "val_ratio": 0.0},        # 与 W3 同侧（§8.1）
    "will-general": {"select": lambda r: (r.get("meta") or {}).get("forge_cat") == "will-general",
                     "expect": 80, "val_ratio": 0.2},
})

# 防双计：这些组的行不进 re / route / discipline / gen（否则 forge2 的 kb-re 与 will-rev 会被 re 组再吃一遍）
EXCLUDE_FORGE = {"forge", "forge2", "will-rev", "will-nsfw", "will-tech", "will-general"}

# 同侧硬规则（INTEGRATION §8.1 + D2 推论）
VAL_RATIO_OVERRIDE = {"will-tech": 0.0, "will-nsfw": 0.0}   # 两组都全量进 train
# 且 min_val 保护对这两组跳过，否则 0 行 val 会触发 FATAL
```

**收尾断言（三条都要）**
```python
assert sum(g["total"] for g in groups.values()) + ungrouped == len(rows), "组和≠总行"
assert all(got[k] == EXPECT[k] for k in EXPECT if EXPECT[k] is not None), f"配额不符 {got}"
assert got["will-rev"] == 120, "D1 未生效：will-rev 选到 0 行"          # ← 专门为 D1 加的
```

**`plan_layers.CAT_TO_DIR` 追加**
```python
CAT_TO_DIR.update({
    "will-rev": "will-rev-train", "will-nsfw": "will-nsfw-train",
    "will-tech": "will-tech-train", "will-general": "will-general-train",
})
# 注意：CAT_TO_DIR 只让决策树"看得见"，不会自动加权；
#       seg() 里必须显式 cats_to_mix({...}) 把这四个加进去，否则登记了也不进 batch。
```

---

## 6 落地顺序（一条命令一行，全在本仓库内）

```bash
# 1) 切分（新增文件，不动既有 10 个 subsets；D1 的选择器必须已在 make_intent3_subsets 里）
python scripts/make_intent3_subsets.py --out-dir data/subsets
# 1b) 断言：will-rev total=120（D1）、will-tech val 文件 0 行（同侧）、Σ组 == 语料行数
python scripts/make_subsets.py --verify-only
# 2) 权重表（D3/D5：由脚本生成，不手抄；唯一实现 tmp/v41/）
python train/lines/27b-kittyrev/kitty-rev/tmp/v41/gen_mix_table.py --nsfw <w3_accept 的 n> --rest 1.6 --json logs/v41/mix.json
# 3) act-cache（全量重算，v4 的缓存因 base 不同而无效）
python scripts/precompute_activations.py ... --out act-cache-v41 --expect-base-fp <fp>
# 4) 训练（--data-mix 用 §3.2 生成的串）
```

---

## 7 五条不许动（沿用 INTEGRATION §7，全部仍然有效）

```text
1) data/large-mix-plus/train.jsonl（sha16 b90a1ae8a8b5519b）—— v4 单变量的锚
2) data/subsets/ 里既有 10 个文件 —— 重切会废掉 v4 的 act-cache
3) make_subsets 的默认参数 —— 必须显式 --out-dir
4) W5 探针（refuse-probe40）—— 永不进任何 subsets
5) W2 DPO（will-dpo）—— 不进 act-cache，走独立偏好训练路径
```

---

## 8 本清单的自检

```bash
C:/ProgramData/anaconda3/python.exe train/lines/27b-kittyrev/kitty-rev/tmp/v41/gen_mix_table.py --nsfw 150 --rest 1.6
# 期望（D7 口径）：Σ组 == 5378（恒等式 ✓）；rest 42.71%（正常，边距 0.71pp）；
#                  forge 26.56%（带内）；will-* 4.81%（<10%）；327 行处 rest 破 42%
C:/ProgramData/anaconda3/python.exe train/lines/27b-kittyrev/kitty-rev/tmp/v41/gen_mix_table.py --nsfw 150 --rest 1.6 --no-weight-small
# 对照（D5 口径，775 行零曝光）：rest 46.15% · forge 28.70% · will-* 5.20%
C:/ProgramData/anaconda3/python.exe tmp/wf2/check_w3n.py   # G1-G7（含 D2 双 selector 等价）
C:/ProgramData/anaconda3/python.exe tmp/wf2/check_w4.py    # H1-H9
C:/ProgramData/anaconda3/python.exe tmp/wf2/selftest_all.py  # 一键 6 项（S4 = rest/forge 联动断言）
```

**联动断言（§4.1 的脚本化）**：`selftest_all.py` 的 S4 同时检查
`rest ≥42` **且** `25 ≤ forge ≤ 40` **且** `will-* <10` **且** `Σ组 == 语料总行` **且** 边界表存在；
只报单个数字的调参结论，按未交付处理。

---

## 9 语义脚注（lead 要求写进表里）：本地 --data-mix vs 云端全量

```text
本文件 §3/§4 的所有占比，都基于「本地 train_partial_lora 的原生 --data-mix 语义」：
  权重 = 采样概率比，行数 = 语料行数，两者相乘得到"有效权重"。

若 v4.1 改走云端全量 train_kitty：
  ① 该训练器**没有权重机制**（F2 今日已证实）→ 权重只能转成"行复制份数"
     （例：forge 4 = 把 forge 行复制 4 份；rest 1.6 ≈ 复制 1.6 份，需取整成 2 或用混合池）
  ② 云端**均匀采样**，route/discipline/gen 775 行**天然已包含**，不存在"零曝光"问题
     → D7 那三个 1 的权重在云端是"本来就有的"，不必额外动作
  ③ 因此本表的占比**不能直接套到云端**：云端的分母是行复制后的总行数，需按份数重算

一句话：本表 = 本地权重的规格；云端 = 行复制份数的规格。两条路的表不可混用。
```



---

## D6 · W3 用 80/20（train 120），不全量 —— lead 2026-10-22 裁决
> 编号说明：本节原标 "D5"，与 lead 同日的 **D5 = 唯一基数** 裁决撞号，改为 **D6**（内容未改）。


**裁决**：`VAL_RATIO_OVERRIDE` 保持 `{"will-tech": 0.0}`，**不追加 will-nsfw**。W3 按标准 80/20 切分。

**两条理由（lead 原话，落档）**
```text
① rest 40.07%（复核带）vs 39.93%（破 40 线）：前者符合阈值表；后者按纪律「必须调权重」。
② 80/20 给 W3 留 30 条 val —— 这是唯一能测「W3 有没有过拟合」的手段。
   W3 是 base 自生成的，与训练分布同源，本来就最容易过拟合；没有 val 只能靠猜。
```

**与 D4（rest=1.6）叠加后的落点**（两套基数都算，因为 §3 的表与我的表基数不同）

| 基数 | rest | forge（r1+forge2） | comply | re | will-* 合计 | 合计 |
|---|---:|---:|---:|---:|---:|---:|
| A 组 train 行 × 权重 | **51.72%** | **25.68%** | 11.19% | 6.69% | 4.74% | 8582.4 |
| B 语料全量行 × 权重 | **46.15%** | **28.70%** | 12.48% | 7.47% | 5.20% | 9616.4 |

（A = comply 320×3 / forge (384+167)×4 / re 287×2 / will-rev 96×2 / nsfw 120 / tech 30 / general 64 / rest 2774×1.6）

**⚠ 口径已闭合，且已被 D7 再覆盖（willing-forge-2，2026-10-22 16:0x）**：脚本已交到本工作区
`train/lines/27b-kittyrev/kitty-rev/tmp/v41/gen_mix_table.py`（`tmp/wf2/gen_mix_table.py` 为转发壳，实现只有一份）。
判读口径演进：A 栏（切分后 train 行）**按 D5 作废** → B 栏（语料全量行）成立 →
但 B 栏当时把 775 行按 0 计，**D7 已给它们权重 1**，故**现行数 = §3.2 的 rest 42.71% / forge 26.56%**。
本节下面的 46.15% / 28.70% 保留作"D5 未给 775 行权重"时的证据。

**D6（80/20）对现行表的影响（实测 0.12pp，不影响判读）**

| W3 计法 | will-nsfw 行 | 合计行 | 有效权重合计 | rest | forge |
|---|---:|---:|---:|---:|---:|
| 全量口径（语料行，D7） | 150 | 5378 | 10391 | 42.71% | 26.56% |
| D6 采样口径（80/20 后 train） | 120 | 5348 | 10361 | **42.83%** | **26.64%** |



**执行落点**：`tmp/v41/build_v41_corpus.py --with-w3 <w3-sft 文件>` → `tmp/v41/apply_patch_and_dryrun.sh`，
预期 Σ组 **2604**（2454+150）、will-nsfw **120/30**、空组断言消失、dry-run rc=0。
