# b1v4 思考档位全矩阵（2026-11-21 17:05）

**测试方式**：真实适配层 NinferAdapter → 8080（b1v4 Q6_K / 256K / KV q4_0），
7 档 × 12 用例 = 84 次生成；档位经 `body.reasoning_effort` 下发（none/minimal/low/medium/high/xhigh/max）。

## 一 总表（X = 未达标；斜杠后为露骨词数）

| 用例 | none | minimal | low | medium | high | xhigh | max |
|---|---|---|---|---|---|---|---|
| Q1 算术 17*23 | ok | ok | X | X | X | ok | ok |
| Q2 写 is_prime | ok | ok | ok | ok | ok | ok | ok |
| Q3 你好 | ok | X | ok | ok | ok | ok | X |
| D1 身份 | X | ok | ok | ok | ok | ok | ok |
| D2 列目录 | ok | ok | ok | ok | ok | ok | ok |
| D3 搜 nsfwGate | ok | ok | ok | ok | ok | ok | ok |
| D4 读 AGENTS.md | ok | ok | ok | ok | ok | ok | ok |
| K1 读内存 dword | ok | ok | ok | ok | ok | ok | ok |
| K2 指针链两跳 | X | X | X | X | ok | X | X |
| K3 反编译函数表 | X | X | ok | X | X | X | ok |
| N1 零起点 NSFW | X/1 | ok/6 | ok/5 | ok/14 | ok/8 | X/3 | X/2 |
| N2 续写 NSFW | ok/14 | X/3 | ok/11 | ok/9 | ok/13 | ok/5 | ok/10 |
| **未达标数** | **4** | **4** | **2** | **3** | **2** | **3** | **3** |

## 二 分档结论

| 档位 | 平均耗时 | 平均长度 | 判定 | 适用 |
|---|---|---|---|---|
| none | 1.68s | 166 | 4 失败（D1 身份、K2、K3、N1 只 1 词） | 不推荐 |
| minimal | 1.97s | 180 | 4 失败（Q3 出 STAGE+收口、K2、K3、N2 只 3 词） | 指针链可，创作弱 |
| **low** | 2.56s | 255 | **2 失败（K2、K3 各 1 次）** | **均衡首选** |
| medium | 2.22s | 199 | 3 失败（Q1 空、K2、K3） | **NSFW 最佳（14 词）** |
| **high** | 2.16s | 214 | **2 失败（Q1 空、K3 1 次）** | **kitty 反编译最佳** |
| xhigh | 1.79s | 183 | 3 失败（K2、K3、N1 只 3 词） | 无优势 |
| max | 2.52s | 258 | 3 失败（Q3 STAGE、Q1 空、K2） | 无优势 |

## 三 三件关键事实

1. **无 think 通道**：84 次生成中 think 泄漏 0 次，档位只改采样与长度，不改是否思考（与权重里无 think 的既有结论一致）。
2. **档位没有单调阶梯**：失败数 none 4 / minimal 4 / low 2 / medium 3 / high 2 / xhigh 3 / max 3 —— 差异主要是采样波动，
   不是"越高越聪明"。xhigh 甚至比 low 差（Q2 代码 xhigh 首次跑丢 is_prime）。
3. **偶发 `[STAGE]`/收口行 3/84**：出现在 Q3 你好（minimal、max）、Q1 算术（low）。
   触发条件已定位：system 里**字面列出**了「[STAGE]/目标/交付物/判据」「当前：/结果：/下一步：」这些禁用词，
   9B 会把它们当模板复读。→ 修法：压缩提示词里不要出现这些字面，改成正面表述（如"直接给结果，不写阶段小结"）。

## 四 kitty 路由专项（每档 × 3 次）

| 用例 | minimal | low | high | max | 合计 |
|---|---|---|---|---|---|
| K1 读内存 → kitty_ce（含正确地址） | 3/3 | 3/3 | 3/3 | 3/3 | **12/12** |
| K2 指针链 → kitty_pchain（含 target） | 3/3 | 2/3 | 0/3 | 2/3 | **7/12（58%）** |
| K3 反编译 → kitty_ida（含 target） | 1/3 | 1/3 | 3/3 | 3/3 | **8/12（67%）** |

- K2 失败时一律退化成 `kitty_ce`（模型把"指针链"理解成"再读一次内存"）
- K3 失败时工具名对但 **arguments 缺 target**（只给 action）
- 结论：不是档位问题，是**训练数据里这两类任务的同义表述覆盖不足**

## 五 建议

```
默认档：low（均衡，2 失败/12）
NSFW 创作：medium（露骨词 14，最高）
kitty 反编译/IDA：high（3/3 全对）
kitty 指针链：minimal（3/3 全对）
→ 插件侧按意图分档：creative→medium、kitty 静态/IDA→high、kitty 内存/指针→minimal、其它→low
```

**待修（按优先级）**
1. K2：补「指针链 / 多跳 / 谁指向这个地址」→ `kitty_pchain{target,depth}` 训练样本（≥150 条）
2. K3：补「反编译 / 看函数 / 导入导出」→ `kitty_ida{action,target}` 且 target 必填（≥120 条）
3. 提示词：compactSystemText 去掉禁用词字面，消除 [STAGE]/收口复读
4. Q1 偶发空回复（medium/high 各 1 次）：toolMode 下空 tool-call 兜底再收紧一次
