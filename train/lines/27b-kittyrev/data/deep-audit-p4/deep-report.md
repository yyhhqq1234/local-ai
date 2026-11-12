# 27B 深度缺陷审查 — gen3_1p4-nsfw-kitty.jsonl

- 行数 **32556** · ctx **2048** · tokenizer **精确**

## 缺陷计数

| 规则 | 计数 | 含义 |
|---|---|---|
| D11_ctrl_or_mojibake | 17 | 零宽/控制符/乱码 |
| D14_meta_open | 3 | 答案以元话术开头 |
| D15_ascii_in_cjk | 1704 | 中文类目里英文占比>80% |
| D6_self_repeat | 599 | 8-gram 重复率>0.35（复读倾向） |
| D9_residue | 1270 | 环境/TODO/占位残留 |

## D1 角色序列

- 无 system 行：**1797** · system 不在首位：**0** · 孤儿 tool：**414**

  - `system→user→assistant` × 30754
  - `user→assistant` × 1698
  - `user→assistant→tool→assistant→tool→assistant` × 25
  - `user→assistant→tool→assistant→tool→assistant→tool→assistant` × 19
  - `user→assistant→tool→assistant` × 17
  - `user→assistant→tool→assistant→tool→assistant→tool→assistant→tool→assistant` × 15

## D2 tools 覆盖（关键）

- tools=null 行：**32556** / 32556（100.0%）
- tools 非空行：**0**
- 有 tool_calls 但 tools=null：**0** → 模型看到 tool_call 结果却从未见过 schema

## D5 长度分布（token）

- p50 **213** · p90 **1047** · p99 **1360** · max **2082**
- 超 ctx 2048：**1** 行

## D8 模板霸屏

- 唯一答案 8228 种；重复答案行合计 **24328**（占 74.7%）

| 次数 | cat | 开头 |
|---|---|---|
| 3481 | scene | `当前为常规模式（未授权成人向内容），不输出露骨性描写。  可以按这个口径继续：同题材的非露骨` |
| 76 | tool-route | `<tool_call> {"name": "kitty_ce", "arguments": ` |
| 56 | tool-route | `kitty_pchain action=pchain  选它的理由：Kitty多跳反查（通道` |
| 52 | tool-route | `kitty_engines action=route  选它的理由：engine route` |
| 52 | tool-route | `kitty_acescan action=acescan  选它的理由：反作弊对抗日一键编排` |
| 52 | tool-route | `kitty_dualview action=dualview  选它的理由：三视图取数门禁（` |
| 50 | real-trajectory | `这条不能这么走。KM_MODE off 只清标志位，CE 没有真正的回退 API —— 要如` |
| 48 | op-syntax | `这条不能这么走。S_NEW 必须给显式区间，缺了回 ERR\|need-range；单窗 ≤` |
| 45 | tool-route | `<tool_call> {"name": "kitty_ce", "arguments": ` |
| 44 | real-trajectory | `这条不能这么走。P_BACK 同样必须显式窗口，缺了回 ERR\|need-range，命中` |

## D12 门控

- 拒绝语变体数：**1920**
  - 3481 × `当前为常规模式（未授权成人向内容），不输出露骨性描写。  可以按这个口径继续：同题材的非`
  - 50 × `这条不能这么走。KM_MODE off 只清标志位，CE 没有真正的回退 API —— `
  - 48 × `这条不能这么走。S_NEW 必须给显式区间，缺了回 ERR|need-range；单窗 `
  - 44 × `这条不能这么走。P_BACK 同样必须显式窗口，缺了回 ERR|need-range，命`
  - 44 × `这条不能这么走。KM_PW 默认拒绝：实测物理写会卡死 Lua 引擎（宿主活着但 tic`

## 每类画像

| cat | 行数 | token p50 | token p90 | 拒答行 |
|---|---|---|---|---|
| tool-route | 16283 | 204 | 354 | 728 |
| kb-re | 5561 | 192 | 262 | 715 |
| cont | 3426 | 374 | 1152 | 2538 |
| scene | 1375 | 234 | 1149 | 1024 |
| real-trajectory | 1305 | 196 | 433 | 100 |
| multi | 1043 | 938 | 1305 | 763 |
| general | 1030 | 1025 | 1150 | 0 |
| op-syntax | 726 | 184 | 219 | 87 |
| style | 667 | 929 | 1438 | 485 |
| <none> | 462 | 199 | 346 | 25 |
| expand | 346 | 532 | 1437 | 259 |
| kb-tool | 190 | 188 | 347 | 179 |
| glossary | 142 | 196 | 228 | 77 |

## D3 工具名出现频次（取前 25）

- `kitty_ce` × 10796
- `kitty_patch` × 4539
- `kitty_ghidra` × 2368
- `kitty_sym` × 1994
- `kitty_ops` × 1596
- `kitty_prot` × 1110
- `kitty_ida` × 1084
- `kitty_die` × 950
- `kitty_km` × 871
- `kitty_x64dbg` × 862
- `kitty_dump` × 823
- `kitty_dbg` × 677
- `kitty_net` × 570
- `kitty_drv` × 450
- `kitty_wpb` × 444
- `kitty_dualview` × 401
- `kitty_status` × 392
- `kitty_pchain` × 378
- `kitty_settings` × 378
- `kitty_frida` × 374
- `kitty_acescan` × 351
- `kitty_loop` × 328
- `kitty_jadx` × 311
- `kitty_asm` × 300
- `kitty_rea` × 299
