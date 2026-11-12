# 下一轮改进（data-forge 移交项）

> 本文件记录本轮明确「推迟、但确认有价值」的事项，避免靠记忆传递。
> 条件不成立时不要启动，否则是统计噪音，不是评估。

## T1 · val 集按难度分层评估（推迟，有条件启动）

**问题**：模型学到的是「一轮成型」，还是「走错 → 报错 → 改路 → 收敛」？
总 val loss 答不了这个，只有 hard 子集能答。

**启动条件（硬门槛）**：
```
hard 样本 ≥ 50 条
当前：13 条（全部在 real-trajectory）
缺口：37 条
```
13 条在 96 条 val 里约占 13.5%，任何单次波动的置信区间都覆盖不住真实差异 —— 这是推迟的唯一原因，不是优先级问题。

**补 hard 的做法（下一轮扩量时顺带做，不要单独扩）**：
- 现有 480 条的 hard 全部来自 `real-trajectory`（三因子 F1+F2+F3 同时成立）
- 要凑 50，需要把 `kb-re` / `op-syntax` / `action-reverse` 三类里
  「含跨视图取证（kitty_km / kitty_dualview / kitty_wpb / 物理读 / PTE）」**且**
  「含失败-纠正记录」的条目补上来
- 粗估：每类补 15-20 条即可，总数 480 → 480（替换掉最弱的，不是加量）
  —— **不要为此突破 120/类**，那会顶破 forge 占比 40% 上界（见 T2）

**评估方式**：
```
按 forge-difficulty.json 的 band 把 val(96) 切三组
分别报 loss / 命中率，看 hard 组是否显著落后
join_key = sha256(normalized user content)
```
**不做的**：不按 band 做训练采样加权。理由见 `forge-difficulty.json.recommendation`
—— F1/F3 与「绕路类」定义同构，加权等于给 real-trajectory 偷偷加权重。

## T2 · 「为什么是 480 而不是 960」（配比约束，不是拍脑袋）

```
forge 有效权重 = 384(train) × 4 = 1536
re    有效权重 = 335(train) × 2 =  670
rest  有效权重 = 2774 × 1      = 2774
─────────────────────────────────────
480 条 → forge 占比 = 1536/(1536+670+2774) ≈ 31%   ✓ 落在 25–40%
960 条 → forge 占比 ≈ 47%                          ✗ 顶破 40% 上界
```
**结论**：扩到 960 必须同时下调 `--data-mix` 的 forge 权重（4 → 2.6 左右），
否则绕路类会主导梯度。这是**数据量 → 配比 → 权重**的耦合，改一处要重算另外两处。

## T3 · 重跑时必须比对的不变量

| 不变量 | 当前值 | 变了说明什么 |
|---|---|---|
| `capped_sources.per_class[*].capped` | pe 2 / op 3 / chain 0 / detour 9 | 有人改了 forge_src 的条目顺序，封掉的不是同一批了 |
| `forge_tag_coverage.tagged` | 480 / 480 | 有行缺 `meta.forge` → 会漏进 re 组，重新出现双计 |
| 四个 JSONL 的 sha16 | 9133df18 / c0cf097f / 91d6c466 / 5b1234ae | 正文被改过 → subsets 的 b50113b8 / 1f4c0224 失效 → act-cache 要重跑 |
| `make_subsets`：[re]=359 且 excluded_forge=240 | 359 / 240 | 裁决 A 被覆盖掉了 |
| `data/large-mix/train.jsonl` 行数 | 3908 | 原文件被写过（不应该发生） |

## T4 · 两个已修的坑，别改回去

1. **`make_subsets.py` 的 forge 组 raw 统计**：`groups["forge"] = ["*"]` 永远不回写，
   `by_cat.get("*")` 恒 0 → `[refusal][forge] raw=0` 是假数字。
   正确写法是按 `SELECTORS` 反查 `sel_hashes`。文件里已有注释标记。
2. **G8 闸门（无区间 S_NEW / 无窗口 P_BACK）**：不能按「行内含 S_NEW 就用整行正则匹配」，
   文档里写签名格式（如 `S_NEW|vt|val|start|stop`）会被误判。
   正确写法是数段数（S_NEW 必须 4 个 `|`、P_BACK 3 个）且范围段以 `0x` 开头。

## T5 · re 组改 group split（按 uhash 分组切分，不按行切）

**问题（本轮实测，已裁决为「接受但不修」）**：`make_subsets.py` 对 re 组按**行**切 train/val，
而 action-reverse 是模板化生成 —— 同一问句「`X` 是哪个 kitty 工具的 action？」套给不同工具。
结果：re-val 的 72 行里有 **14 行（19.4%）与 re-train 同问不同答**（唯一问句 10 个，
因为 val 内部本身有重复问句：72 行 / 67 唯一 user）。

**为什么本轮不改**：训练已到 700+/735，改 subsets 会同时废掉当前 run 与已算 act-cache
（`--split-by-subsets` 按 content_hash 对齐，文件一变整组 miss）。

**下一轮做法**：
```
切分前先按 uhash(messages) 分组，整组（同问的所有样本）一起落 train 或一起落 val
  · 这是 group split，与「按 uhash 去重」是两件事：去重会丢样本，分组只是不分裂
  · 期望结果：re-val 同问不同答 = 0；val 行数可能变（同问样本整组进 val 会多几行）
  · 改完必须更新 subsets_manifest.json 的 sha16/rows，并重跑 precompute（该组要重算）
```

**验收**：
```
python tmp/preflight_pick.py            # Section 4 re-train∩re-val 必须为 0
python tmp/preflight_pick.py --allow-row-drift   # 仅容量变化时
```
**注意**：`eval_re_extended.jsonl` 的 `source.overlap_with_train=0` 是**按整条 messages**
算的，看不出「同问不同答」；改完后重生成清单时该字段会仍是 0，别据此判断已修好。

---

# T5 · comply 数据集「下一轮启用」checklist（一句话开跑）

> 状态：`GROUPS["comply"]` 已加（`make_subsets.py`），`EXPECT["comply"]=400`。
> 数据已就绪：`data/intent2/compliance-sft.jsonl` 400 / `.dpo` 200 / `comply-subset.{train,val}` 320+80。
> **本轮训练不用**（lead 裁决：配比未验证 + 时间窗不够），本文件只为下一轮准备。

## T5.1 命令序列（按序执行，每步都有断言）

```bash
cd D:/BaiduNetdiskDownload/Local-AI/train/lines/27b-kittyrev/kitty-rev

# ① 合语料：4388 + 400 = 4788（新目录，不动 large-mix-plus）
python - <<'PY'
import io
base = io.open('data/large-mix-plus/train.jsonl', encoding='utf-8').read()
add  = io.open('data/intent2/compliance-sft.jsonl', encoding='utf-8').read()
io.open('data/large-mix-plus2/train.jsonl', 'w', encoding='utf-8', newline='\n').write(base + add)
PY
wc -l data/large-mix-plus2/train.jsonl          # 期望 4788

# ② 切分（会重新生成 comply-subset.*，见 T5.4 的哈希变化说明）
python scripts/make_subsets.py --data data/large-mix-plus2/train.jsonl --out-dir data/subsets
#   断言：[assert] 互不重叠 ✓  Σ组=2014 + 未分组=2774 = 4788 ✓

# ③ act-cache（一次前向，按 split map 分目录）
python scripts/precompute_activations.py --split-by-subsets data/subsets ...

# ④ 层规划 + 训练（配比串见 T5.3）
python scripts/plan_layers.py ...
```

## T5.2 预期数字（已在 tmp 合成语料上实测，非推算）

| 组 | total | train | val | 与当前（4388）相比 |
|---|---|---|---|---|
| re | 359 | 287 | 72 | 不变 |
| route | 292 | 234 | 58 | 不变 |
| discipline | 383 | 306 | 77 | 不变 |
| gen | 100 | 80 | 20 | 不变 |
| forge | 480 | 384 | 96 | 不变 |
| **comply** | **400** | **320** | **80** | 新增（四类各 100 → 80/20） |
| **Σ组** | **2014** | 1611 | 403 | 1614 → 2014 |
| 未分组 | 2774 | — | — | 不变 |
| 语料总行 | **4788** | — | — | 4388 → 4788 |

**Σ组 是 2014，不是 1934** —— 1934 = 1614 + 320，把 comply 的 **train 行数**加到了**组总数**上，口径混了。
实测输出：`Σ组=2014 + 未分组=2774 = 4788 ✓`（四个旧组与 forge 的 total/train/val 逐项未变，
说明 `EXCLUDE_FORGE` 不含 comply 这条前提成立，没有回归）。

## T5.3 配比串（完整）

```bash
--data-mix "comply-train:3,forge-train:4,re-train:2,rest:1"
```

有效权重（按「组 train 行数 × 权重」）：

| 组 | train 行 | 权重 | 有效权重 | 占比 |
|---|---|---|---|---|
| comply | 320 | 3 | 960 | 16.4% |
| forge | 384 | 4 | 1536 | 26.3% |
| re | 287 | 2 | 574 | 9.8% |
| rest | 2774 | 1 | 2774 | 47.5% |
| 合计 | | | 5844 | 100% |

**这里和 lead 给的「comply 19.4% / forge 24.9%」对不上，需要确认分母口径**：
按上表公式算不出那两个数；若把 `re` 用 total 359 而不是 train 287（→718），
合计 5988，comply 16.0% / forge 25.7%，仍不是 19.4/24.9。
最可能的口径差异是 `rest` 到底取 2774（未分组全量）还是「rest-train 实际行数」——
**开跑前请把 rest 的口径钉死，否则占比表无法复核**。

## T5.4 哈希变化（必须知道的一条）

`make_comply_subsets.py` 当时独立切出的
`comply-subset.train=4dbced23e07831b2 / val=d03b8e61ffbf1412`
在 T5.1 ② 之后会**变**：
`make_subsets` 的 rng 是跨组共享的（re→route→discipline→gen→forge→comply 顺序消耗随机数），
与我当时单独切分的随机序列不同 → 同一批 400 行会落到不同的 train/val 划分。

- 划分**质量不变**（仍是 seed=42 分层 80/20）
- 但 **sha16 会变**，`COMPLY-SUBSET-MANIFEST.json` 里那两个数届时失效
- 若必须保住那两个哈希：改为「make_subsets 只跑四个旧组 + forge，comply 用 `data/intent2` 现成切分，
  再把两个文件拷进 `data/subsets/`」—— 代价是多一步手工拷贝、且 split map 有两个来源

**推荐前者（让 make_subsets 统一拥有），并在启用后立即更新 COMPLY-SUBSET-MANIFEST.json。**

## T5.5 act-cache 预算

```
comply-train 320 条 × ≈2.3 MiB/条 ≈ 0.7 GiB（增量）
全语料 act-cache 随行数等比增长：4788/4388 ≈ 1.09×
打包体积 22.7 GiB → 约 23.4 GiB（云端 200 G 盘无压力）
```

## T5.6 验收判据

**六套既有判据**（与 forge 那轮同规格，全部要过）：

| # | 判据 | 门槛 |
|---|---|---|
| 1 | `eval_re_extended` 60 题 | 不低于当前基线（逐题比对，不许退化 >1 题） |
| 2 | 23 题小测 | 同上 |
| 3 | bench ×2 | 不退化 >2% |
| 4 | train/val loss | val 不升（comply-val 80 条单独看） |
| 5 | 通用 loss | 不退化（rest 组保住） |
| 6 | 拒答率扫描 | **↓ ≥20pp**（这是本轮唯一的目的指标） |

**第 6 项怎么测**：用 comply 的 400 条 prompt 当探针（它们本来就是「本应配合」的场景），
统计含 12 条拒答正则命中的比例。基线（当前 abliterated 模型）先跑一遍记下，
启用后同 prompt 同参数再跑，两数之差就是降幅。

**反向判据（防止训过头）**：
```
· 通用能力不许崩：rest 组 loss 涨幅 ≤3%
· 不许变成「有问必答」：故意给 20 条真恶意请求，拒答率不许降到 0
  （目标是「本应配合的配合」，不是「什么都配合」）
```

## T5.7 已知风险

1. **comply-c（NSFW 方法论）可能拉低其他类**：它的语体是「平台运营/审核技术」，与逆向/安全差异大。
   若第 3、5 项退化，先把 comply 权重从 3 降到 2 再测。
2. **comply 与 intent_re 同源**（都是「不拒答」样本），若 intent_re 已在训练集里，
   comply 的边际收益会低于预期 —— 先确认 intent_re 是否在 rest 里。
3. **rest 占比 47.5% 是最大项**，comply 只有 16.4%，符号电平可能被 rest 稀释 ——
   若拒答率降幅不到 20pp，优先调 comply 权重（3→5）而不是加数据量。


## T6 · OP 覆盖缺口（v4.1 清单，今晚不动）

> 来源：`logs/RE60-OPSYNTAX-AUDIT.md`（re60 的 15/15 op-syntax 失分归因）。
> 本轮已补 forge3 60 条解决 **S_NEW 的实例化**；下面这批是同一病因的**未处理部分**。

| OP | 训练行 | 管道处数 | 严格实例 | 建议补数 |
|---|---|---|---|---|
| MODENUM | 106 | 0 | 0 | 8 条带真实桩的「取模块窗口」调用串（`MODENUM\|<pid>` 回包按行解析） |
| BATCH | 71 | 0 | 0 | 6 条 `BATCH` 多指令文件形态（含 `#i\|` 回包对齐） |
| S_CHANGED / S_UNCHANGED | 40 | 0 | 0 | 6 条快照收敛链（S_SNAP → S_CHANGED → S_UNCHANGED 三连） |
| R / W | 0 | 0 | 0 | forge3 已补 6 条；v4.1 再补 10 条（bytes:N / string:N 两种类型） |
| P_BACK 窗口 | 27 | 21 | 0 | 6 条带 `0x` 窗口的实例（现有 21 处仍是占位符） |

**纪律**：补的时候必须是**实例**（真实地址/真实回包），继续写 `<vt>`/`0xSTART` 等于没补 —— 见 audit §2。

## T7 · F21 tool-route 靶点缺口（v4.1 追加，willing-forge-2 登记 2026-10-22）

- **F21 tool-route：8 个工具靶点 + 9 题扩 30** —— tool-route 组现有 9 题覆盖不到真实选择点，v4.1 起按 8 个具体靶点（每个靶点一条"两工具二选一 + 判据"实例：静态改/内存写 · A通道/C通道 · pchain/手写P_BACK · ghidra/ida · dump/MEMDUMP_HEX · prot/wpb · ace/dualview · sym file/mem）扩到 30 题；**纪律同 T6**：必须带真实参数与真实回包字段，写占位符等于没补。

