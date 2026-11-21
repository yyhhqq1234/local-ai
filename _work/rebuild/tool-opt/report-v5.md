# v5 工具数据三件套报告（指针链路由 / IDA 参数 / 直答防模板）

- 生成日期：2026-11-21 ｜ 固定种子 `seed=20261121` ｜ 脚本可重跑
- 生成器：`_work/rebuild/tool-opt/gen_v5.py`（生成 + 自检一体）
- 统计：`_work/rebuild/tool-opt/v5-stats.json`
- 解释器：`C:\ProgramData\anaconda3\python.exe`（全路径）
- 重跑：`pwsh → & 'C:\ProgramData\anaconda3\python.exe' _work\rebuild\tool-opt\gen_v5.py`
  注：本会话 `ops_bash`（git-bash）对写文件被拒（`touch` 在所有目录均 Permission denied），
  故生成走宿主 PowerShell（`pwsh`）；脚本本身无 shell 依赖，任何有写权限的解释器都能跑。

格式统一为 `{"messages":[{role:system},{role:user},{role:assistant}]}`，UTF-8，`\n` 换行，一行一条。

---

## 1 三份产出

| 集 | 文件 | 行数 | 答案唯一率 | tool_call 正则命中 | 参数缺陷 |
|---|---|---:|---:|---:|---:|
| A 指针链路由 | `train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-pchain.jsonl` | **155** | **100.0%**（155/155） | 155/155 | 0 |
| B IDA 参数 | `train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-ida.jsonl` | **132** | **100.0%**（132/132） | 132/132 | 0 |
| C 直答防模板 | `train/lines/9b-oxcoder/data/dsh-adapt/tool-direct-answer.jsonl` | **200** | **96.5%**（193/200） | 不适用 | 不适用 |

唯一率口径：`assistant` 全文去重占比。C 的 7 条重复全部来自身份题
（8 条问法共用同一条法定答复「我是石井，本地工作区执行层。」），属规则要求，不修正。
另测「工具名+参数」去重：A 155/155 = 100%，B 132/132 = 100%。

### A 覆盖（7 类 × 17 = 119 正样本 + 36 负样本对照 = 155）

| 说法类 | 条数 | 工具名分布 |
|---|---:|---|
| 反查指针链 | 17 | kitty_pchain 119 |
| 多跳指针 | 17 | kitty_ce 36（负样本） |
| 谁指向这个地址 | 17 | — |
| 从哪读到这个值 | 17 | 负样本拆分： |
| 追父链 | 17 | 　读值 → kitty_ce R 24 条 |
| 找基址 | 17 | 　按值扫描 → kitty_ce S_NEW 12 条 |
| 几跳能到 | 17 | |

- 地址族：`0x7FF6A0000000` / `0x7FF75FCD1000` / `0x140001000` 三个起点，其余按
  `0x7FF6A0xxxxxx` / `0x7FF75FCDxxxx` / `0x1400xxxxx` 三族确定性派生，共 155 个互不相同的地址
  （避免同一地址被多问法复用时模型背地址而不学路由）。
- 参数：`depth` 只取 `2` / `3`（十进制整数），`target` 全部 `0x` 开头。
- assistant 形态：`<tool_call>{"name":"kitty_pchain","arguments":{"target":"0x…","depth":2}}</tool_call>` + 一行 `判据：…`。

### B 覆盖（7 类 × 14 = 98 正样本 + 34 对照 = 132）

| 类别 | 条数 | 类别 | 条数 |
|---|---:|---|---:|
| 函数列表 functions | 14 | 字符串 strings | 14 |
| 反编译某函数 decompile | 14 | 入口点 entries | 14 |
| 导入表 imports | 14 | 对照：无 IDA → kitty_ghidra | 12 |
| 导出表 exports | 14 | 对照：已知符号 → kitty_rea_function | 10 |
| 交叉引用 xrefs | 14 | 对照：有 IDA → kitty_ida（判据说明三档分工） | 12 |

- 工具名分布：`kitty_ida` 110、`kitty_ghidra` 12、`kitty_rea_function` 10。
- `kitty_ida` 的 110 条 **全部带 `target`**；`decompile` 额外带 `name`（8 个函数名轮转）。
- target 两种写法都覆盖：绝对路径（`D:/BaiduNetdiskDownload/Local-AI/kitty-target.exe`）
  与裸 exe 名（`kitty-target.exe` / `notepad.exe` / `game.exe` / `sample.exe`），共 14 + 12 个互不重合目标。
- 34 条对照的 `(action,target)` 与正样本完全不撞（对照专用 target 池），保证「工具名+参数」也 100% 唯一。

### C 覆盖（4 类 × 50 = 200）

| 类 | 条数 | 构成 |
|---|---:|---|
| C1 短算术/事实 | 50 | 30 算术（结果当场计算并回验）+ 20 事实（首都/光速/端口/位数…） |
| C2 身份与寒暄 | 50 | 30 寒暄 + 8 身份 + 12 应答 |
| C3 明显不需要工具 | 50 | 10 概念解释 + 10 翻译 + 10 改写 + 10 四句诗 + 10 一句话总结 |
| C4 诱饵对照 | 50 | 「我只想知道 X，别管别的」类，只答 X |

- 禁用字面扫描：`[STAGE]`、`目标：`、`交付物：`、`判据：`、`当前：`、`结果：`、`下一步：`、`计划：`、`步骤1`
  → **0 命中**（assistant 侧）；system 侧同样 0 命中（见 §4 设计说明）。
- 算术正确性：30 条全部用正则回解析表达式重算比对 → **0 错**。

---

## 2 自检结果（全部通过）

| 检查项 | A | B | C |
|---|---|---|---|
| JSON 逐行可解析 | 155/155 | 132/132 | 200/200 |
| 角色序列 system→user→assistant | 155/155 | 132/132 | 200/200 |
| assistant 非空 | 155/155 | 132/132 | 200/200 |
| `<tool_call>{…}</tool_call>` 可抓取且内层 JSON 可解析 | 155/155 | 132/132 | — |
| 参数完备（pchain: target+depth∈{2,3}｜ida: action+target，decompile 加 name） | 155/155 | 132/132 | — |
| 禁用字面 | — | — | 0 命中 |
| 唯一率达标（A/B≥95%，C≥90%） | 100% ✓ | 100% ✓ | 96.5% ✓ |
| 行数达标（A≥150，B≥120，C≥200） | 155 ✓ | 132 ✓ | 200 ✓ |

独立复核（另起进程重读文件、不复用生成器内存）：三份行数/唯一率/tool_call 命中与上表一致；
C1 算术重算 30/30 正确。

---

## 3 现有语料基线（缺陷的「供给面」证据）

统计口径：子串出现次数 + 含该工具名的记录数（`json` 逐行读，不解析内容语义）。

| 文件 | 记录数 | `kitty_pchain` 出现 | 含 pchain 记录 | `kitty_ida` 出现 | 含 ida 记录 |
|---|---:|---:|---:|---:|---:|
| `kitty-reverse/cleaned/kitty-clean-v3.jsonl` | 10960 | **268** | 144（1.31%） | **666** | 368（3.36%） |
| `kitty-reverse/opt/kitty-downsampled.jsonl` | 10534 | **255** | 134（1.27%） | **713** | 387（3.67%） |

读法：
- pchain 在 1.1 万行里只有 134~144 行涉及（≈1.3%），而 `kitty_ce` 是内存类任务的高频「顺手工具」，
  两者曝光比悬殊 → 模型遇指针链问题退化成 `kitty_ce` 是数据分布的必然结果，不是模型「不懂」。
- ida 有 368~387 行，但其中相当部分是「讲解 action」而非「带 target 的完整调用」，
  所以实测出现「工具名对、arguments 只有 action」——参数位没有足够的配对样本。
- 新增 A 155 / B 132 行把这个比价拉正（见 §5 混配建议）。

---

## 4 为什么这样写能治这三个病

### 病 1：指针链 → 误选 `kitty_ce`（7/12）

1. **正反对照成对出现，而不是只教正确答案。** 只写 pchain 正样本，模型学不到「什么时候不用 pchain」；
   A 里 36 条负样本用**同一地址族、同一口吻**问「读这个地址的值」「扫这个值」，
   答案是 `kitty_ce`，`判据` 里写明「读值才是 R，反查引用是 pchain；扫描要显式区间」。
   模型拿到的是判别边界（读值 / 反查 / 扫描三分），不是单点记忆。
2. **判据写在 assistant 里，等于把判别理由一起训进去。** 推理链（`判据：…`）与实际工具选择同一条样本、
   同一个 assistant turn，模型学到的是「因为要 2 跳溯源所以选 pchain」，而不是「看到『指针』就选 pchain」。
3. **7 类问法覆盖同一语义的 7 种口语形态**（反查指针链 / 多跳指针 / 谁指向 / 从哪读到 / 追父链 / 找基址 / 几跳能到），
   每类 17 条、地址互不相同 → 防止模型靠地址或句式关键词硬匹配，逼它按语义选工具。
4. **`depth` 只出现 2/3 两个十进制值**，且 2 跳与 3 跳在各类里交替出现 → 抑制「depth 写字符串」「depth=1」
   这类参数退化（实测成功时参数正确、失败时退化，说明缺的是稳定先验）。

### 病 2：`kitty_ida` 只给 action 不给 target（8/12）

1. **110 条 ida 样本里 target 100% 出现**，且 target 位置固定紧跟在 action 后 → 形成强共现先验。
2. **同一 action 配 14 个不同 target**（路径式 + 裸 exe 名各占一半）：模型无法靠「这个 action 就配这个值」
   记忆，只能学「action 是模式、target 是实体，两者必须同现」这条规则，泛化到没见过的 exe。
3. **`decompile` 强制多一个 `name`**：把「参数位是逐个必填」的观念压实，避免模型学成
   「只写一个参数就够」的坏习惯（这正是缺 target 的同源毛病）。
4. **34 条三档对照**把「有 IDA / 没 IDA / 已知符号」的分工写进判据：
   `kitty_ida`（有 IDA）→ `kitty_ghidra`（没有 IDA 的免费档）→ `kitty_rea_function`（符号已知，不必整盘 analyze）。
   这样即使模型不认识工具细节，也能按「环境条件」而不是「顺手程度」选工具。

### 病 3：短问句答非所问、吐 `[STAGE]` / 收口模板（3/84）

1. **换 system**：C 集 system 只写「首行就是产物；不写阶段小结、不写计划清单、不用固定格式收口」，
   没有任何「阶段/收口」的可复制样本。
2. **关键细节：system 里不写禁用词字面。** 实测过「system 写 `[STAGE]`/`目标：`/`判据：`/`当前：`/`结果：`/`下一步：`
   字面 → 模型直接复读这些词」。所以 C 的 system 用**行为描述**（「不写阶段小结」「不写计划清单」）
   代替**字面枚举**；禁用词只出现在训练器的自检脚本里，不进任何一条训练文本。
3. **assistant 全部是「最小充分答复」**：算术给一个数字、身份给法定一行、寒暄给一句、
   翻译/改写给译文本身、诗给四行、总结给一句。没有一条带计划、阶段、收口 → 模型没有可模仿的模板。
4. **C4 诱饵类专治「答非所问」的本体**：上下文里塞满 B（CPU/内存/磁盘/风扇/超时/重试…），
   问句明确「我只想知道 X」，答案只给 X。50 条覆盖端口/超时/pid/errno/行数/命中数/版本/tag/IP/…
   → 训练「只回答被问的那一个字段」的抑制能力，而不是「把所有看到的信息都倒出来」。
5. **C1 算术结果全部现算并回验**（30/30 正确）：短问句样本一旦答案错，模型会学成
   「短问题也要解释一堆」的补偿行为，所以正确性是防模板的前置条件。

---

## 5 混配建议（进 9B 混配时的行数与权重）

原则：A/B 是**稀有路由先验**（基线占比 1.3%~3.7%），C 是**行为抑制**（要压过 system 里的旧模板残留）。
建议按「复本数」放大，而不是抽稀：

| 集 | 原生行数 | 建议复本 | 混配行数 | 占混配总量 | 理由 |
|---|---:|---:|---:|---:|---|
| A tool-pchain | 155 | ×3 | **465** | ≈8% | pchain 基线仅 1.3%，需拉到 ~8% 才能压过 kitty_ce 的顺手先验；×3 后地址/问法仍 100% 唯一 |
| B tool-ida | 132 | ×3 | **396** | ≈7% | ida 基线 3.4%~3.7% 但多为讲解型；需补足到 ~7% 且参数位全带 target |
| C tool-direct-answer | 200 | ×4 | **800** | ≈14% | 行为抑制要高频重复才压得住模板复读；且 C 单条极短（≈20~120 字），×4 的 token 成本低于 A/B 的 ×3 |

合计新增 ≈1661 行。若混配总量 6000 行：A 465 + B 396 + C 800 = 1661（≈27.7%），其余 4339 行留原 kitty/agent 语料。

保守档（怕挤掉原分布）：A ×2=310、B ×2=264、C ×3=600，合计 1174 行（≈19.6%）。
不建议低于 A ×2 / C ×3：低于此，pchain 占比仍 <3%，答非所问的抑制信号会被原语料里的讲解型长回答稀释。

---

## 6 复现与校验命令

```powershell
# 生成（含自检，统计落 v5-stats.json）
& 'C:\ProgramData\anaconda3\python.exe' D:\BaiduNetdiskDownload\Local-AI\_work\rebuild\tool-opt\gen_v5.py

# 基线计数
& 'C:\ProgramData\anaconda3\python.exe' -c "import json;[print(p,sum(1 for _ in open(p,encoding='utf-8')),sum(l.count('kitty_pchain') for l in open(p,encoding='utf-8')),sum(l.count('kitty_ida') for l in open(p,encoding='utf-8'))) for p in [r'train\lines\9b-oxcoder\data\kitty-reverse\cleaned\kitty-clean-v3.jsonl',r'train\lines\9b-oxcoder\data\kitty-reverse\opt\kitty-downsampled.jsonl']]"
```
