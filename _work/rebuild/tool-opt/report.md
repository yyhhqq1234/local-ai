# 9B 工具调用数据优化报告（近邻判别 / 同义增广 / 曝光校正）

- 生成日期：2026-11-21（固定种子 seed=20261121，脚本可重跑）
- 训练用 system（DSH 段，逐字）与答案协议：`<tool_call>{"name":…,"arguments":{…}}</tool_call>`，arguments 扁平、action 作为值。
- 答案唯一率口径：`工具名 + arguments 规范化 JSON` 去重后的占比；同时要求「同一答案不得套用 >2 条问法」。

## 0 实测失败与根因

| 任务 | 期望工具 | 实测给出 |
|---|---|---|
| 数一下 md 文件有几个 | ops_bash | ops_glob |
| 搜一下 nsfwGate | ops_grep | kitty_find（幻觉名，清单无此工具） |
| 把 AGENTS.md 里的 foo 改成 bar | edit | read |
| 锁定目标并写会话目标 | kitty_settings | kitty_rea_call_path（应为 kitty_rea_callpath） |
| 反编译 kitty-target.exe 看函数 | kitty_ida | kitty_rea_function |
| 取 0x7FF6A0000000 的三视图 | kitty_dualview | kitty_ce |

根因三条（数据侧）：

1. **工具调用密度过低**：三份 kitty 语料 11441 行里只有 222 行带 tool_call（1.9%），且文本面工具（ops_* / read / write / edit）仅 9 条，模型学不到「文本任务用文本工具」的先验。
2. **缺少近邻对照**：数据里每个工具都是孤立讲解，没有「同一语义下 A 与 B 怎么分工」的成对样本，模型只能用『顺手的那个』（kitty_ce / read / ops_glob）。
3. **名字漂移无惩罚**：语料里出现 `kitty_find`、`kitty_rea_call_path` 这类清单里不存在的写法而没有被纠正样本，模型把幻觉名当合法工具名输出。

## 1 A. 近邻工具判别集

- 文件：`train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-neighbor.jsonl`
- 行数：**149**（每组 20–24 条）
- 答案唯一率：**100.0%**（重复率 0，>2 次重复的答案 0 个）
- 格式校验：全部首行 `<tool_call>` + 第二条 `判据：…`（149/149 通过），参数全部扁平标量

| 组 | 易混对 | 条数 |
|---|---|---|
| G1 | ops_grep vs kitty_find(幻觉) / kitty_ce FIND | 22 |
| G2 | ops_glob vs ops_bash(ls/find) vs kitty_static | 20 |
| G3 | edit vs write vs read | 24 |
| G4 | kitty_ida vs kitty_ghidra vs kitty_rea_function | 22 |
| G5 | kitty_dualview vs kitty_ce(R) vs kitty_km | 20 |
| G6 | kitty_settings vs kitty_trail vs kitty_loop | 21 |
| G7 | kitty_patch vs kitty_asm vs kitty_dump | 20 |
| — | 合计 | 149 |

判别要点（写进每组 assistant 的判据行，这里只摘主干）：

| 易混对 | 一句话判据 |
|---|---|
| ops_grep vs kitty_find / kitty_ce(FIND) | 磁盘文本 → ops_grep(pattern+path)；进程内存值 → kitty_ce S_NEW；kitty_find 不存在，不生成。 |
| ops_glob vs ops_bash vs kitty_static | 要清单 → ops_glob；要计数/排序/管道 → ops_bash；要看 PE 静态面（字符串/节/熵/证书）→ kitty_static。 |
| edit vs write vs read | 改局部 → edit(old_string 命中唯一)；整篇定稿/新建 → write；只取一段 → read(offset/limit)。 |
| kitty_ida vs kitty_ghidra vs kitty_rea_function | 整 PE 建库+全量查询 → kitty_ida；无 IDA 档位 → kitty_ghidra；既有索引里的单函数取证 → kitty_rea_function(procedure)。 |
| kitty_dualview vs kitty_ce(R) vs kitty_km | 同址三视图对账 → kitty_dualview；单路取值/写值 → kitty_ce R/W；内核态 attach/PA 翻译/物理读 → kitty_km。 |
| kitty_settings vs kitty_trail vs kitty_loop | 落双字段/状态机 → kitty_settings；过程留痕 → kitty_trail；整轮 8 站流水 → kitty_loop。 |
| kitty_patch vs kitty_asm vs kitty_dump | 磁盘 PE 字节改写(带 expect) → kitty_patch；算机器码/相对跳转 → kitty_asm；内存落盘/镜像重建 → kitty_dump。 |

产物内工具分布：`{'kitty_dualview': 7, 'kitty_km': 5, 'kitty_patch': 9, 'kitty_ghidra': 4, 'ops_grep': 18, 'kitty_dump': 6, 'kitty_rea': 3, 'kitty_settings': 13, 'kitty_ida': 9, 'kitty_loop': 5, 'kitty_rea_compare': 1, 'ops_glob': 8, 'ops_bash': 7, 'write': 6, 'read': 6, 'edit': 12, 'kitty_rea_function': 4, 'kitty_ce': 12, 'kitty_asm': 5, 'kitty_static': 5, 'kitty_trail': 3, 'kitty_rea_callpath': 1}`

## 2 B. 同义任务增广

- 文件：`train/lines/9b-oxcoder/data/kitty-reverse/opt/tool-synonym.jsonl`
- 行数：**338**
- 答案唯一率：**100.0%**（>2 次重复答案 0 个）
- 表述覆盖：口语（“数一下…”）、省略句（“logs 里有哪些 .log”）、带目标条件（“只限 docs 下 / 只看最近十条”）、带错误前置状态（“刚才提交失败了…”“manifest 格式有没有坏”）

| 工具 | 条数 | 参数面 |
|---|---|---|
| ops_grep | 50 | pattern+path(+include) |
| edit | 50 | file_path+old_string+new_string(+replace_all) |
| write | 50 | file_path+content |
| read | 50 | file_path+offset+limit |
| ops_bash | 47 | command+description |
| kitty_settings | 47 | action+target/sessionGoal/taskTransition |
| ops_glob | 44 | pattern+path |
| 合计 | 338 | — |

## 3 C. kitty 数据工具曝光分布

统计口径：三份文件合计 11441 条记录，其中 8211 条提到至少一个工具名；含 tool_call 的记录占比 **1.9%**。

| 工具 | 提及次数 | 记录覆盖 |
|---|---|---|
| kitty_ce | 4064 | 2004 |
| kitty_patch | 1546 | 766 |
| kitty_ops | 809 | 698 |
| kitty_ghidra | 806 | 438 |
| kitty_sym | 772 | 474 |
| kitty_ida | 564 | 309 |
| kitty_prot | 472 | 317 |
| kitty_dbg | 415 | 217 |
| kitty_km | 372 | 200 |
| kitty_x64dbg | 371 | 233 |
| kitty_net | 369 | 201 |
| kitty_drv | 357 | 208 |
| kitty_dump | 352 | 213 |
| kitty_loop | 338 | 183 |
| kitty_die | 336 | 218 |
| kitty_acescan | 316 | 185 |
| kitty_wpb | 297 | 195 |
| kitty_status | 296 | 183 |
| kitty_rea | 292 | 156 |
| kitty_pchain | 277 | 150 |
| kitty_settings | 269 | 147 |
| kitty_gdre | 268 | 112 |

**结论**：kitty_rea 家族记录覆盖 653 条 = **8.0%**（提及占比 5.6%），**未超过 15% 阈值** → 不需要为家族做下采样。实测里 kitty_rea_function 抢走 kitty_ida 的任务，不是「曝光过量」，而是它缺少对照样本（见 §1 G4 组）与全量建库成本不可见。

**真正超线的是 kitty_ce**：记录覆盖 2004 条 = **24.4%**，是六道失败题里 3 道的默认落点。按 15% 上限下采样，比例 **0.546**（约保留 55%），下采样后文件 10534 行（原 11441 行，未覆盖原始）。

下采样命令（可重跑）：

```powershell
# 默认：kitty_rea≤15% + kitty_ce≤15%
C:\ProgramData\anaconda3\python.exe _work/rebuild/tool-opt/audit_dist.py
# 只想动家族、不碰 kitty_ce
C:\ProgramData\anaconda3\python.exe _work/rebuild/tool-opt/audit_dist.py --caps kitty_rea=0.15
```

## 4 10 道验收题与预期答案

| # | 任务 | 预期工具 | 预期 arguments | 判别依据 |
|---|---|---|---|---|
| 1 | 数一下 md 文件有几个 | `ops_bash` | `{"command":"find docs -name '*.md' \| wc -l","description":"数 docs 下 md 文件个数"}` | 计数是 shell 管道，不是 ops_glob 清单 |
| 2 | 搜一下 nsfwGate | `ops_grep` | `{"pattern":"nsfwGate","path":"."}` | 仓库文本检索；kitty_find 不存在，kitty_ce 只搜内存值 |
| 3 | 把 AGENTS.md 里的 foo 改成 bar | `edit` | `{"file_path":"AGENTS.md","old_string":"foo","new_string":"bar"}` | 局部替换用 edit；不是 read 后再 write |
| 4 | 锁定目标并写会话目标 | `kitty_settings` | `{"action":"target-set","target":"kitty-target.exe","sessionGoal":"定位血量指针链"}` | 双字段落盘只有 settings target-set |
| 5 | 反编译 kitty-target.exe 看函数 | `kitty_ida` | `{"action":"analyze","target":"D:\\DrCE(26.2.16)\\KittyDebugTool\\DBG\\DBG64\\loaddll.exe"}` | 整 PE 建库=kitty_ida analyze；单函数档案才 rea_function |
| 6 | 取 0x7FF6A0000000 的三视图 | `kitty_dualview` | `{"addr":"0x7FF6A0000000","vt":"dword","samples":3}` | 三路对账=dualview；单路取值才是 kitty_ce R |
| 7 | 列一下 docs 下所有 md 文件 | `ops_glob` | `{"pattern":"**/*.md","path":"docs"}` | 只要路径清单=ops_glob |
| 8 | 读 PATCHES.md 第 120 行往后 40 行 | `read` | `{"file_path":"plugins/dsh-local-ai/PATCHES.md","offset":120,"limit":40}` | 区段读=read offset/limit |
| 9 | 新建 _work/rebuild/tool-opt/notes.md 写三行 | `write` | `{"file_path":"_work/rebuild/tool-opt/notes.md","content":"# 备注\nA 近邻集\nB 同义集\n"}` | 新文件整篇落地=write；改局部才是 edit |
| 10 | 把「三视图门禁全绿」这条记进探索轨迹 | `kitty_trail` | `{"action":"append","target":"kitty-target.exe","step":"dualview","text":"0x7FF6A0000000 三视图一致，samples=3"}` | 过程留痕=trail append；状态迁移才 settings |

判分口径：名字 + action 命中对 0.6，arguments 关键键（路径/模式/地址/pattern）对 0.4；6/10 为现基线，目标 ≥9/10。

## 5 新混配建议

单轮工具调用部分建议 **1200 行**（与下采样 kitty 语料按 1:6 采样进 batch，工具行约占 token 的 14%）：

| 桶 | 行数 | 占比 | 来源 |
|---|---|---|---|
| 文本/文件面（ops_bash/ops_grep/ops_glob/read/write/edit） | 480 | 40% | B 同义集 338 + 现有 9 + 补 133 |
| 近邻对照（A 判别集，含幻觉名纠正） | 180 | 15% | A 149 + 补 31 |
| kitty 逆向主面（ida/ghidra/ce/patch/dump/static/sym/dbg） | 300 | 25% | 下采样语料 + 现有 tool_call |
| 会话工作台（settings/trail/loop/status） | 120 | 10% | B 中 settings 47 + 现有 |
| kitty_rea 家族（上下文字段取函数档案） | 60 | 5% | 从现密度降到 5%，避免抢单 |
| 负样本/无工具/拒答（含 kitty_find 类幻觉名纠正） | 60 | 5% | 新造 |
| 合计 | 1200 | 100% | — |

配比三条硬规则：

1. **文本任务不得再输给 kitty**：任何「搜/数/读/改」类 user 句，assistant 必须是 ops_grep / ops_bash / read / write / edit，A 组数据就是这个护栏。
2. **kitty_rea 家族不做默认入口**：只在 user 明说「已知符号 / 已有索引 / 走 REA」时出现，占工具桶 5%。
3. **每个工具每轮至少 1 条近邻对照**：A 组按 batch 轮转插入，防止再次收敛到单点默认。

## 6 复现

```powershell
cd D:\BaiduNetdiskDownload\Local-AI
C:\ProgramData\anaconda3\python.exe _work/rebuild/tool-opt/gen_neighbor.py   # A
C:\ProgramData\anaconda3\python.exe _work/rebuild/tool-opt/gen_synonym.py    # B
C:\ProgramData\anaconda3\python.exe _work/rebuild/tool-opt/audit_dist.py     # C
C:\ProgramData\anaconda3\python.exe _work/rebuild/tool-opt/build_final.py    # D 校验+报告
```

## 7 假设与边界

- ops_grep / ops_glob 为部署档工具名（等价于 glob/grep 语义），参数按 `pattern`/`path`/`include` 拼；
- 地址样本以实测基址 `0x7FF6A0000000` 为锚，其余为同模块内偏移（占位，不指向真实数据语义）；
- 真实 PID 取自本机实测：explorer 10236 / node 1716 / pwsh 11500；
- PE 目标用真实文件（`D:\DrCE(26.2.16)\KittyDebugTool\…`，只读引用；补丁类样本一律指向工作区内副本路径，不在 DrCE 写任何字节）；
- 未启动训练、未占 GPU；仅生成与统计。
