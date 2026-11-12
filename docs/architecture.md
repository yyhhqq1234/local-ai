# 架构 · 适配器 · 优化日志

> 合并自：01-architecture.md、02-local-model-adapter.md、05-optimization-log.md


---

## 01-architecture.md

# 01 · 架构与数据流

## 1 组件关系

```
┌──────────────────────────────────────────────────────────────┐
│ DeepSeek Harness (DSH)                                        │
│  ├─ agent loop（决定是否继续下一步；finish kind 影响它）        │
│  ├─ llm 路由表 llm.adapters: Map<provider, {adapter,...}>      │
│  │    └─ "ninfer" → NinferAdapter（本仓库插件注册）           │
│  ├─ tools 注册表（238 个全局工具）                             │
│  └─ session 记录（session.v4.jsonl.zstd，多帧 zstd）           │
└───────────────┬──────────────────────────────────────────────┘
                │ OpenAI 兼容 /v1/chat/completions (SSE)
┌───────────────▼──────────────────────────────────────────────┐
│ NInfer 引擎 127.0.0.1:1234                                     │
│  · 模型 Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-     │
│    IQ2_S-mtp.ninfer（9.53 GiB）                               │
│  · deviceKV 36864 token 页池 / hostKV 7168 MiB / kvDtype nvfp4│
│  · prefillChunk 512 / draftTokens 3（MTP）/ maxContext 262144 │
│  · vision=cpu（图片走 CPU 编码）                              │
└───────────────┬──────────────────────────────────────────────┘
                │ CUDA（sm120, 2407MHz SM / 11001MHz MEM）
┌───────────────▼──────────────────────────────────────────────┐
│ RTX 5070 Ti Laptop 12,227 MiB                                 │
│  有效带宽实测 ≈675 GiB/s → decode 天花板 675/9.53 ≈ 70.8 tok/s │
└──────────────────────────────────────────────────────────────┘
```

## 2 一次请求的完整路径

```
1) 用户在 GUI 选 provider=ninfer, model=qwen3.8-27b-ablit-swift15-iq2s
2) DSH 组 system（工作区约定 + 技能清单<available_skills> + 工具说明段）
3) 调 NinferAdapter.stream(options)
   ├─ toOpenAIMessages()           DSH content blocks → OpenAI messages
   ├─ slimSkillsBlock()            <available_skills> 折叠（所有消息，不只 system）
   ├─ dedupeSystem()               system 内同名同内容段去重
   ├─ stripToolHints()             剔除白名单外工具的使用说明（js-reverse / jobs）
   ├─ offloadLargeToolResults()    >1200 字符的工具输出落盘 _work/toolout/，只留头尾
   ├─ annotateToolErrors()         ERR|CODE → 追加 [建议下一步]
   ├─ detectRepeatedToolCalls()    空转告警（≥3 同结构 / ≥4 失败）→ 注入 system
   ├─ stuckBreaker                 硬熔断（≥6 / ≥6）→ 不请求模型，直接 finish=error
   ├─ filterTools()                238 → 16（toolAllowlist）
   ├─ pickSampling()               code/creative/fact/default 四档
   ├─ effortCap                    ≤medium 尊重，high/xhigh/max 压到 medium
   ├─ 长产物任务 → max_tokens ≥16384
   └─ 写 stats 行（tools/systemChars/totalChars/sample/effort/payloadBytes）
4) 引擎 SSE 流 → adapter 转 StreamChunk
   ├─ block-start / reasoning-delta / text-delta / tool-call-delta(带 index)
   ├─ block-end（必须带累积全文，否则 DSH 显示空白）
   ├─ usage（数值字段；不能有 undefined）
   └─ finish（stop / max-tokens / error）
5) DSH 依 finish kind 决定：继续下一步（stop）｜终止（error）｜续写（max-tokens）
```

## 3 端口与进程

| 项 | 值 |
|---|---|
| 引擎 | `127.0.0.1:1234`（`ninfer-serve.exe`，pid 由 `run/engine.pid` 记录） |
| DSH Web GUI | 由 dsh 启动时分配（如 60276 / 53042，见运行时上下文） |
| 插件加载方式 | dsh-super-injector 注入（`registry.json`），或 profile 的 `dsh-ninfer-local` 条目 |
| 引擎日志 | `ninfer-csunx/logs/engine-<ts>.log` |

## 4 关键数据文件

| 文件 | 说明 |
|---|---|
| `_work/session-audit/ninfer-stats.jsonl` | 每请求一行，用于核对裁剪/采样/档位 |
| `_work/session-audit/s{N}.jsonl` | 会话解帧产物（zstd 多帧 → JSONL） |
| `~/.dsh/sessions/<proj>/session-<id>/session.v4.jsonl.zstd` | DSH 原始会话（多帧 zstd，需逐帧解） |

## 5 解帧方法（会话分析入口）

```bash
# 多帧 zstd：单次 zstdDecompressSync 只解第一帧，必须按 magic 切片逐帧解
node _work/session-audit/unframe2.mjs <session.v4.jsonl.zstd> <out.jsonl>
# 帧 magic：28 b5 2f fd
```


---

## 02-local-model-adapter.md

# 02 · 本地模型适配器（NinferAdapter）

> 源码：`plugins/dsh-ninfer-local/src/adapter.ts`｜运行时：`lib/index.js`（补丁直接落这里）

## 1 职责

把 NInfer 的 OpenAI 兼容 SSE 转成 DSH 的 `StreamChunk`，并在**只影响 provider=ninfer** 的前提下做
上下文瘦身、行为护栏与采样分流。云端 provider 各有 adapter，不经过本文件。

## 2 StreamChunk 契约（DSH 侧硬要求）

| chunk | 必填字段 | 坑 |
|---|---|---|
| `block-start` | `index`(非负整数), `blockType`(text/reasoning/tool-call) | index 不能重复 |
| `reasoning-delta` | `index`, `text` | index 必须等于对应 block-start 的 index |
| `text-delta` | `index`, `text` | 同上 |
| `tool-call-delta` | **`index`(必须)**, `id`, `argumentsDelta` | 缺 index → 整轮 error：`tool-call-delta index must be a non-negative safe integer` |
| `block-end` | `index`, **`block` 必须是完整内容** | 传 `text:''` → 前端"回复被吞"（正文空白） |
| `usage` | 数值字段，**不能有 undefined** | `|| undefined` → `Assistant stream chunk must be losslessly JSON-serializable` |
| `finish` | `reason.kind` | `stop`=DSH 继续下一步；`error`=终止本轮；`max-tokens`=可能续写 |

**块序号规则**：reasoning 占 0 → text 占其后 → tool-call 用 `blockBase + tIdx`（否则撞车丢块）。

## 3 上下文瘦身链（顺序即代码顺序）

```text
slimSkillsBlock    <available_skills> → 技能名（限 60 条）；对所有消息生效（清单在 user 消息里）
dedupeSystem       同名同内容 markdown 段去重；只对 system
stripToolHints     白名单外工具的使用说明整段剔除（当前 js-reverse / jobs；kitty 保留）
offloadLargeToolResults  >1200 字符工具输出落盘；read/ops_grep/ops_glob/edit/write 例外
annotateToolErrors  ERR|CODE 追加 [建议下一步]
detectRepeatedToolCalls  空转告警（同结构≥3 或失败≥4）
stuckBreaker       硬熔断（同结构≥6 或失败≥6）→ 不请求模型，直接 finish=error
filterTools        238 → 16
```

实测效果：system 30,164 → 23,179 字符；payload 118KB → 46KB；首字 165s → 13.9s。

## 4 采样分流

| kind | 触发关键词 | temperature | top_p | presence_penalty |
|---|---|---|---|---|
| code | 代码/脚本/函数/html/css/json/sql/正则/部署 | 0.2 | 0.95 | 0 |
| creative | 写/创作/小说/文案/诗/故事/剧本/散文 | 0.8 | 0.92 | 0.3 |
| fact | 解释/什么是/为什么/区别/原理/计算/对比 | 0.1 | 0.90 | 0 |
| default | 其余 | 0.6 | 0.95 | 0 |

取最后一条 user 消息匹配（兼容 content 数组）。`sampling.enabled=false` 可整体关闭。

## 5 思考档

```text
effortCap = 'medium'：
  none/minimal/low/medium → 原样发送（尊重用户选择）
  high/xhigh/max          → 压到 medium（防 8K 预算被思考吃光）
defaultEffort = 'minimal'（模型选择器初始档）
```

> 历史教训：曾用 `forceReasoningEffort: 'minimal'` 硬覆盖，导致用户选 medium 实际跑 minimal，测试结论失真。

## 6 动态输出预算

长产物任务（完整/详细/长文/3000字/HTML/SVG/整段代码…）→ `max_tokens` 提到 ≥16384；其余用 DSH 传入值。

## 7 空交付处理

```text
finish=max-tokens 且无正文 → 补一条可见文本：
  「本轮只产出思考，正文被 max_tokens 截断；建议重发或把任务拆小」
（否则前端表现为完全空白）
```

## 8 崩溃与回滚

```text
每次改动前：cp lib/index.js lib/index.js.bak-thinkN
改坏时：cp lib/index.js.bak-thinkN lib/index.js && node --check
全链回滚点：.bak-think → .bak-think30 → ... 见 PATCHES.md
禁用 shell 拼字符串改 JSON（多层转义会打断引号，已踩两次）
```

## 9 与 DSH 的注册关系

```text
· llm.adapters 是 Map<provider, {adapter, provider, retryPolicy}>
· 本插件 apply() 时若 registerAdapter=true → ctx.llm.registerAdapter(['ninfer'], new NinferAdapter(profile))
· 热替换：staging 工具 swap_ninfer_adapter*（delete 旧注册 → import 带 ?v= 的新模块 → apply → 验证 ctor）
· dev_reload_package 会用注入时的旧 config，可能不带 registerAdapter → 需要 swap 兜底
```


---

## 05-optimization-log.md

# 05 · 优化纪实（2026-10-20，约 30 轮）

> 记录"做了什么、为什么、结果如何、哪些路子走不通"。失败路径同样重要——避免后人重踩。

## 阶段 0 · 起点病历（会话 `cceef1ab`）

```text
· 首字 165～180 秒（一句"你好"）
· 鹈鹕 SVG 任务：reasoning 烧光 8192 输出预算，正文 0 字，finish=max-tokens
· 两轮同态失败（"继续"后仍 0 字）
· 238 个工具 schema 264KB、skills 清单 75KB、system 30KB（AGENTS.md 注入两遍）
```

## 阶段 1 · 定量诊断

| 测项 | 结果 |
|---|---|
| 前缀 → 首字 | 10,181 tok → 11.5s；17,331 → 20.3s；**94,377 → 144.8s**（≈730 tok/s） |
| 同 prompt 复跑 | cached 94,372 → **0.43s**（引擎缓存只在"完整 prompt 一致/严格前缀链"生效） |
| 预热固定前缀 | **无效**：prewarm 94K 后换问句，cached=0 |
| decode 带宽 | Qwen 9.53GiB → 61.2 tok/s；Bonsai 7.12GiB → 94.8 tok/s → **有效带宽 ≈675 GiB/s** |
| 上下文 → decode | ≤2K 满速；6K 起衰减；30K 时 −28% |

**结论**：decode 天花板 = 675/9.53 ≈ 70.8 tok/s，单卡不换模型无法破 100。

## 阶段 2 · 上下文瘦身

```text
工具 238 → 12 → 14 → 16（+kitty_ce/kitty_ops/kitty_settings/kitty_status）
skills 清单折叠（限 60 条）+ 全消息生效（原先只处理 system，漏了 user 里的注入）
system 段去重 + 剥离白名单外工具说明（js-reverse / jobs）
结果：system 30,164 → 23,179 字符；payload 118KB → 46KB；首字 165s → 13.9s
```

## 阶段 3 · provider 归属（关键纠错）

```text
发现：llm.adapters.get('ninfer').adapter.constructor.name === 'PiAiAdapter'
      → 之前所有瘦身都不在请求路径上（stats 文件从未生成）
修复：desktop profile 删 llm-pi-ai 的 ninfer 段 + 插件 registerAdapter: true
验证：重启后 before/after 均为 NinferAdapter；其它 8 个 provider 未受影响
```

## 阶段 4 · chunk 契约修复（一个个撞出来的）

| 现象 | 根因 | 修法 |
|---|---|---|
| 回复被吞（流里有内容，消息为空） | `block-end` 传 `text:''` | 累积 textBuf/reasonBuf，block-end 传全文 |
| `losslessly JSON-serializable` | `usage` 字段 `|| undefined` | 只放有值字段 |
| 所有工具调用整轮失败 | `tool-call-delta` 缺 index | 按 id 分配 + block index 顺延 |
| 工具输出膨胀 | 无旁路 | >1200 字符落盘，只留头尾 |
| 落盘→read→再落盘递归 | 旁路未排除内容型工具 | `read/ops_grep/ops_glob/edit/write` 例外 |
| skills 未折叠 | 清单在 user 消息 | 折叠对所有消息生效 |

## 阶段 5 · 行为护栏

```text
executionRules 9 条（工具缺失上报 / 环境事实 / 验收纪律 / 规格核对 / 产物自检 /
                    临时文件 / 落盘勿回读 / kitty 收尾 type 语义 / 错误反应对照）
空转告警：同结构≥3 或失败≥4 → 注入 system
硬熔断：同结构≥6 或失败≥6 → 不请求模型，finish=error
错误码建议：ERR|CODE → [建议下一步]（6 类 + 兜底）
采样分流：code 0.2 / creative 0.8 / fact 0.1 / default 0.6
思考档：effortCap=medium（尊重 ≤medium，压 high/xhigh/max）
```

## 阶段 6 · kitty 专项（最曲折）

| 会话 | 步数 | 结果 | 病灶 |
|---|---|---|---|
| （原始） | 41 | abort | 白名单无 kitty，提示却教它用 → 翻源码自造桥接 |
| `c4ea1e55` | 32 | abort | offload→read 递归 + 提示没写 task-close |
| `3197072f` | 22 | completed | task-dispatch 穷举 10 次 |
| `c8d64024` | **1044** | abort | **熔断用 finish=stop，DSH 不终止** |
| `db680526` | **12** | completed | 只剩 1 次漏 generation + 1 次多余 task-get |

kitty 侧修复（操作者完成）：schema 补 `taskTransition` 的 12 种 `type`、`task-close` 不接参数、错误码带指导。

## 失败路径清单（别重试）

```text
✗ decode 破 100 tok/s        —— 带宽上限 675 GiB/s ÷ 9.53 GiB = 70.8
✗ draftTokens 6 / 0          —— 6 更慢（80/74 tok/s）、0 启动失败
✗ maxContext 降到 32K        —— 与 deviceKV 36864 冲突，kv_capacity 超范围
✗ prefillChunk=1024          —— 需 1.9GB runtime workspace，显存只剩 1.6GB
✗ 预热固定前缀加速首字        —— 该引擎只认完整 prompt 一致/追加式前缀链
✗ 整份删除 v5.7 约定          —— 会丢独有的"路径记录"小节
✗ 熔断用 finish=stop         —— DSH 继续下一步，造成 1044 步死循环
✗ forceReasoningEffort 硬覆盖 —— 吞掉用户档位选择，测试结论失真
✗ shell + node -e 改 JSON 字符串 —— 多层转义打断引号，两次把 lib 打成语法错误
```

## 当前基线与验收工具

```text
首字（冷/热）        13.9s / 0.12s
decode              52～61 tok/s
system 字符          23,179～24,541
payload             46KB～69KB（随历史增长）
kitty 任务步数       12（最好），p90 约 15
验收脚本            _work/session-audit/{bench_speed2,bench_ctx,sim2,verify_*}.mjs
每请求统计          _work/session-audit/ninfer-stats.jsonl
```

## 2026-10-27 · decode 腰斩回归：MTP 投机解码被启动脚本丢掉

现象：`decode 60~70 tok/s` → `30~40 tok/s`，其余设置（deviceKV 36864 / hostKV 7168 / nvfp4 / chunk 512 / draftTokens 3）全部没变。

取证（引擎日志 `req#N done` 行的 `mtp accepted` 字段是判据）：

| 时间 | decode | mtp accepted | 说明 |
|---|---|---|---|
| 10-20 22:12 | 71.3 tok/s | 109/135 (80.7%) | MTP 生效 |
| 10-24 23:18 | 63.4 tok/s | 115/248 (46.4%) | MTP 生效 |
| 10-25 18:18 | 24.1 tok/s | 0/288 (0%) | MTP 生效但该内容零接受（长代码 prompt） |
| **10-25 20:39 起** | **40.6 / 36.7 / 35.4 tok/s** | **字段消失** | **MTP 已不在，解码头完全没跑** |
| 10-27 12:37（修前） | 39.4 / 36.1 tok/s | 字段消失 | 同一现象 |

根因：`ninfer-csunx/run-engine.ps1`（mtime **2026-10-25 18:36**）重写时把投机解码参数丢了 ——
脚本有 `-DraftTokens 3` 形参、启动横幅也打印 `mtp: 3`，但 `$engineArgs` 里从未拼 `--spec mtp --draft-tokens N`。
引擎侧 `--help` 原文：`SPECULATIVE DECODING (off by default)` → 不传就是纯单 token 解码，
所以默认掉档 ≈ 1.5×（历史接受率 42~80%）。参数横幅造成的假象让问题看起来像"引擎自己变慢了"。

修复（[run-engine.ps1:93](../../ninfer-csunx/run-engine.ps1)）：

```powershell
if ($DraftTokens -gt 0) { $engineArgs += @('--spec', 'mtp', '--draft-tokens', [string]$DraftTokens) }
```

实测（重启后同一 prompt）：

```text
before  decode 39.4 tok/s   TTFT 58.5s(排队)   mtp 无字段
after   decode 60.2 tok/s   TTFT 0.238s        mtp accepted 68/159 (42.8%)
```

回滚：`Copy-Item run-engine.ps1.bak-nospec run-engine.ps1 -Force`（回落到无 MTP，decode 约 36）。
自动重启+实测脚本：`_work/session-audit/restart-engine-mtp.ps1`（失败自动回退备份启动器）。

顺带记录（未改）：无 MTP 那版实例长时间跑完后每 5s 刷 `demote-other short ... noresident=645` 且
`host 100%`（KVMem 页在 host 侧非驻留）；MTP 重启后该刷屏消失。若再复现，按 KV ring 参数
（window 19456 / retrieve 3840 / sink 12288）与 deviceKV 36864 的配比复查。
