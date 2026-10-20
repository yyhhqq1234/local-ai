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
