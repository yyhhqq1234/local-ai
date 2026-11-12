# 27B 深度缺陷审查 — gen3_1p6-nsfw-kitty.jsonl

- 行数 **16783** · ctx **2048** · tokenizer **精确**

## 缺陷计数

| 规则 | 计数 | 含义 |
|---|---|---|
| D10_empty_but_toolcall | 12 |  |
| D15_ascii_in_cjk | 889 | 中文类目里英文占比>80% |
| D6_self_repeat | 217 | 8-gram 重复率>0.35（复读倾向） |
| D9_residue | 89 | 环境/TODO/占位残留 |

## D1 角色序列

- 无 system 行：**0** · system 不在首位：**0** · 孤儿 tool：**0**

  - `system→user→assistant` × 16719
  - `system→user→assistant→tool→assistant→tool→assistant` × 19
  - `system→user→assistant→tool→assistant→tool→assistant→tool→assistant` × 12
  - `system→user→assistant→tool→assistant` × 12
  - `system→user→assistant→tool→assistant→tool→assistant→tool→assistant→tool→assistant` × 6
  - `system→user→assistant→tool→assistant→tool→assistant→tool→assistant→tool→assistant→tool→assistant` × 2

## D2 tools 覆盖（关键）

- tools=null 行：**11373** / 16783（67.8%）
- tools 非空行：**5410**
- 有 tool_calls 但 tools=null：**0** → 模型看到 tool_call 结果却从未见过 schema

## D5 长度分布（token）

- p50 **232** · p90 **1137** · p99 **1414** · max **1976**
- 超 ctx 2048：**0** 行

## D8 模板霸屏

- 唯一答案 7740 种；重复答案行合计 **9031**（占 53.8%）

| 次数 | cat | 开头 |
|---|---|---|
| 3476 | scene | `当前为常规模式（未授权成人向内容），不输出露骨性描写。  可以按这个口径继续：同题材的非露骨` |
| 5 | tool-route | `[1] triage —— 横向能力面 kitty_sym action=imports p` |
| 5 | kb-re | `因为那个值只管**旧的**「易受攻击驱动阻止列表」。  实际执行的是 **WDAC 形态**` |
| 5 | tool-route | `一条命令串起来。  kitty_acescan target=<pid或名> module=` |
| 4 | real-trajectory | `这是 OPEN 的回包。  拆字段：首段 OK 是状态位，后面按契约 `OK\|pid[\|` |
| 4 | tool-route | `kitty_dbg 的参数面（共 12 个）： · action（必填） — attach\` |
| 4 | kb-re | `12 个： · S_NEW —— 按值开扫（必显式区间，窗≤16MB/总≤64MB/≤4窗）` |
| 4 | tool-route | `这条不能这么走。DBG_ATTACH 是双层闸门，而且本 build 的 debugProc` |
| 4 | tool-route | `[1] triage —— 找配置载入点 kitty_sym action=imports ` |
| 4 | kb-re | `如果实际加载基址 ≠ imageBase，PE 会应用重定位（.reloc）修正绝对地址。 ` |

## D12 门控

- 拒绝语变体数：**1912**
  - 3476 × `当前为常规模式（未授权成人向内容），不输出露骨性描写。  可以按这个口径继续：同题材的非`
  - 5 × `类型决定比较宽度与解释方式：dword 比 byte 少很多误命中，float 需要按浮`
  - 4 × `这条不能这么走。DBG_ATTACH 是双层闸门，而且本 build 的 debugPr`
  - 4 × `可读/可写探针 LUA（不改变内存：把读到的原字节写回同址）。 注：LUA 沙箱里字符串`
  - 4 × `**旧判据已作废**：HypervisorPresent = True 不能当标准 ——`

## 每类画像

| cat | 行数 | token p50 | token p90 | 拒答行 |
|---|---|---|---|---|
| tool-route | 5805 | 201 | 361 | 260 |
| cont | 3422 | 374 | 1152 | 2534 |
| kb-re | 2450 | 209 | 281 | 308 |
| scene | 1375 | 234 | 1149 | 1024 |
| multi | 1042 | 938 | 1305 | 762 |
| style | 666 | 961 | 1438 | 484 |
| general | 657 | 1014 | 1149 | 0 |
| real-trajectory | 429 | 206 | 539 | 12 |
| expand | 345 | 532 | 1437 | 258 |
| <none> | 222 | 199 | 347 | 12 |
| op-syntax | 171 | 179 | 252 | 16 |
| glossary | 141 | 196 | 228 | 76 |
| kb-tool | 58 | 189 | 385 | 51 |

## D3 工具名出现频次（取前 25）

- `kitty_ce` × 4277
- `kitty_patch` × 1540
- `kitty_ghidra` × 917
- `kitty_sym` × 776
- `kitty_ops` × 701
- `kitty_prot` × 498
- `kitty_ida` × 455
- `kitty_km` × 377
- `kitty_die` × 368
- `kitty_x64dbg` × 318
- `kitty_dbg` × 303
- `kitty_dump` × 303
- `kitty_net` × 210
- `kitty_drv` × 169
- `kitty_dualview` × 154
- `kitty_wpb` × 142
- `kitty_status` × 140
- `kitty_frida` × 140
- `kitty_loop` × 137
- `kitty_settings` × 134
- `kitty_rea` × 130
- `kitty_acescan` × 125
- `kitty_dnspy` × 124
- `kitty_pchain` × 120
- `kitty_asm` × 108
