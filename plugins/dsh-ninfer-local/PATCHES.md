# dsh-ninfer-local · 本地模型专属瘦身改动记录

> 作用域：仅本插件的 `provider`（ninfer / 本地 1234）。云端 provider 各有 adapter，不经过这些改动。
> 原因：本地 12G 卡（RTX 5070 Ti Laptop）上，DSH 默认前缀 94,377 tokens 导致冷 prefill ≈165s（首字慢），
> 且高思考档会把 8,192 输出预算全烧在 reasoning 上、正文 0 字（会话 session-cceef1ab 实测）。

## 当前生效配置（lib/index.js DEFAULT_CONFIG）

| 键 | 值 | 作用 |
|---|---|---|
| `toolAllowlist` | 12 个：write/read/edit/ops_bash/ops_glob/ops_grep/skill/web_search/ninfer_*4 | 工具 schema 264KB → 10KB |
| `slimSkills` | `true` | `<available_skills>` 描述折叠为技能名 |
| `skillNameLimit` | `60` | 技能名只列前 60，其余提示用 find-skills 检索 |
| `slimSystem` | `true` | system 段去重（`[TAG]…[/TAG]` 同名块 + markdown 同名同内容章节） |
| `defaultEffort` | `minimal` | 模型选择器初始档，避免默认 high |
| `forceReasoningEffort` | `minimal` | **请求级强制**：无视 UI 下发的 reasoning_effort |
| `statsPath` | `_work/session-audit/ninfer-stats.jsonl` | 每请求 payload 统计（tools 数 / systemChars / payloadBytes） |

## 函数（lib/index.js，src/adapter.ts 需同步）

- `slimSkillsBlock(system, limit)` —— 折叠技能清单
- `dedupeSystem(system)` —— TAG 块 + markdown 章节去重
- `filterTools(tools, allow)` / `matchAllow(name, allow)` —— 白名单裁剪（支持 `前缀*`）
- `stream()` 中：messages 逐条 slimSkillsBlock + dedupeSystem；tools 走 filterTools；reasoning_effort 走强制档

## 实测（同一 task，冷缓存，RTX 5070 Ti Laptop）

| 版本 | tools | 前缀字符 | prompt tokens | 冷 TTFT |
|---|---|---|---|---|
| 原始 | 238 | 370,578 | 94,377 | **165.4s** |
| v1 | 21 | 53,900 | 15,815 | 19.7s |
| **v2（当前）** | **12** | **38,540** | **11,695** | **14.1s** |

热缓存（同 prompt 复跑）：0.30–0.43s。

## 回滚点

```
lib/index.js.bak-think    # 原始（238 工具、无瘦身）
lib/index.js.bak-think2   # v1（21 工具 + slimSkills）
lib/index.js.bak-think3   # v2（12 工具 + dedupeSystem）
```
回滚：`cp lib/index.js.bak-think3 lib/index.js` → 重载插件或重启 dsh。

## A 方案：provider 归属切换（2026-10-20，已改 profile，待重启生效）

**问题**：`provider=ninfer` 实际由 `llm-pi-ai` 的 `PiAiAdapter` 承载（`llm.adapters.get('ninfer').adapter.constructor.name === 'PiAiAdapter'`），
本插件 `registerAdapter` 默认 `false` → 上面所有瘦身**从未进入请求路径**（会话 56b44334 实测 header tools 仍 238 个 / 264,458B，stats 文件不生成）。

**改动**（工作区外的 `~/.dsh/profiles/desktop/`，已备份 `.bak-armor`）：
```yaml
# cordis.yml 与 cordis.patch.yml 各删 31 行
llm-pi-ai:
  config:
    providers:
-     ninfer:            # ← 整段删除（apiKeyEnv/displayName/api/baseURL/models/streamIdleTimeoutMs/retryPolicy）
-       ...

# cordis.yml 唯一一处
- id: dsh-ninfer-local
  config:
    registerAdapter: true   # ← 新增，让 NinferAdapter 接管 nfer 路由
```

**影响面**：只影响 `provider=ninfer`；nvidia / openai-codex / commandcode×2 / deepseek×2 / codex-local / daseinai 全部不动。
**代价**：图片输入降级为占位文本、重试策略固定 maxRetries=1、无独立 streamIdleTimeoutMs。
**回滚**：
```bash
cp ~/.dsh/profiles/desktop/cordis.yml.bak-armor        ~/.dsh/profiles/desktop/cordis.yml
cp ~/.dsh/profiles/desktop/cordis.patch.yml.bak-armor  ~/.dsh/profiles/desktop/cordis.patch.yml
```
**生效判据（重启后）**：`_work/session-audit/ninfer-stats.jsonl` 出现且 `tools:12`。

## 适配器契约修复（2026-10-20，会话 a34fde6d / 6aa004b2 暴露）

| 现象 | 根因 | 修复 |
|---|---|---|
| 回复被吞（流里有内容，消息正文为空） | 三处 `block-end` 写死 `block.text: ''`；DSH 以 `block-end.block` 作为最终内容 | 累积 `textBuf` / `reasonBuf`，`block-end` 传全文 |
| `Assistant stream chunk must be losslessly JSON-serializable` | `usage.reasoningTokens` / `cacheReadTokens` 用 `|| undefined`，undefined 字段不可无损序列化 | 只放有值字段：`if (rt > 0) u.reasoningTokens = rt` |
| usage 恒为 null | 未开 `stream_options.include_usage` | body 加 `stream_options: { include_usage: true }` |
| 前缀仍偏大（真实会话 payload 118KB ≈ 30K tokens） | skills 清单注入在 **user 消息**（`<system-reminder>`）里，旧逻辑只折叠 `role === 'system'` | 所有消息都折叠 `<available_skills>`；段去重仍只对 system |
| 所有工具调用整轮失败：`tool-call-delta index must be a non-negative safe integer`（会话 7e069ddd turn8+） | `tool-call-delta` 没带 `index`；且 `name: cur.name \|\| undefined` 有 undefined 风险 | 按 id 分配非负整数 index；name 仅在有值时下发；tool-call 块 index 按已用块顺延（`blockBase + tIdx`），避免与 reasoning 块撞 0 |

验证（staging 直连 adapter.stream）：
- `block-end` text 长度：修复前 0 → 修复后 2（"收到"），reasoning 18
- chunk 无损序列化 round-trip 问题数：0
- 18,074 字符的假 skills 块 → 实际发出 `totalChars` 1,022（折叠 94%）

## 提示-工具一致性 + 执行纪律（2026-10-20，会话 ea3a32d0）

| 改动 | 内容 | 依据 |
|---|---|---|
| `stripToolHints: ['kitty']` | 白名单不含 `kitty_*` 时，从 system/user 中剔除 kitty 两段 TOOL LOCK（2,046 字符）与「A 通道速查」段（到 `docs/API-FREEZE.md` 止） | 模型 reasoning 亲口说“工具列表里没有 kitty_ce”，但仍被提示指挥去调，41 步空转后被用户 abort |
| `executionRules` | 向 system 末尾注入 6 条纪律：①工具缺失即上报（禁自造桥接）②环境事实（**PATH 的 python 是 WindowsApps 0 字节占位符；真解释器 `C:\ProgramData\anaconda3\python.exe` = 3.13.9，须全路径**；node 可用；shell 用 pwsh）③验收纪律（回读≤1 次，禁反复 wc -l）④规格核对（字数不够就续写）⑤产物自检（HTML/脚本验一次）⑥临时文件放 `_tmp/` 并清理 | 会话 ea3a32d0 的 M2 震荡（16 步）/M3 盲探（12 步）/M4 字数不足/M6 不自检/D3 shell 用错/D4 垃圾残留 |

实测：样本 system 1,444 字符 → 剥离后 495 → 注入纪律后 **884**（finish=stop 正常）。

> kitty 专项的**彻底方案（薄封装 / 后训练样本）**记录在 `_work/session-audit/KITTY-ISSUE-BACKLOG.md`，按操作者要求留待后训练阶段处理。

## 行为自愈与质量项（2026-10-20 第三轮）

| 项 | 实现 | 验证 |
|---|---|---|
| **B1a 动态输出预算** | 长产物任务（完整/详细/3000字/HTML/SVG/整段代码…）→ `max_tokens` 提到 ≥16384，其余用原值 | 代码审查；避免 reasoning 吃光 8192 后正文为空 |
| **B1b 空交付可见化** | `finish=length` 且只有 reasoning 无正文时，补一条 text：「本轮只产出思考，正文被 max_tokens 截断；建议重发或把任务拆小」 | 实测 `maxTokens=4` → 返回该 38 字符提示，finish=max-tokens（原为空白） |
| **B2 重复调用告警** | 最近 12 次工具调用里，同 `name+参数前140字符` 出现 ≥3 次 → 向 system 追加「重复调用警告」，要求说明阻塞/请求决策/换策略 | 实测 systemChars 565 → 677（+112 注入生效）；修过一次数据源（要用 DSH 原始 messages，转换后 tool_call 在 msg.tool_calls） |
| **B4 旁路阈值收紧** | `offloadToolResultMaxChars` 2000 → 1200 | 更多工具输出落盘，长会话上下文更省 |

未能实施（记录原因）：

| 项 | 原因 |
|---|---|
| A1 `prefillChunk=1024` | 启动失败：`requires 1,964,088,576 bytes, only 1,661,698,048 available`（显存仅剩~1.6GB，chunk 加倍要 1.9GB runtime workspace） |
| A2 历史裁剪 | 需要在 adapter 内做摘要（额外一次请求 ~10s），且可能丢细节，风险高于收益 |
| A3 system 再精准删 | v5.7 副本里含独有的「路径记录」小节，精准删只能省 540 字符 ≈ 0.3s，风险/收益不划算 |
| B3 few-shot | 会 +300 tokens（首字 +0.4s），与「提速」目标冲突，且当前格式遵循已达标（42 条测试） |

## 注意

- `scripts/build.sh` 需要 DSH checkout + tsc，本机不可用；以上改动直接落在运行产物 `lib/index.js`。
  若日后在具备 checkout 的环境重新构建，请按本文件与 `lib/index.js` 现状同步 `src/adapter.ts` 与 `src/index.ts`。
- 白名单里 12 个名字均在 header tools（238）中实际存在，命中率 12/12。
- 若某任务需要 MCP（godot-ai / js-reverse）或 kitty 工具，把相应名字加进 `toolAllowlist` 即可，其它不变。

## 空转熔断误杀修复（2026-10-27，GUI 报「本轮运行失败 STUCK_LOOP」）

现象：本地模型正常干活，会话中途弹出红色「本轮运行失败 STUCK_LOOP」+「处理失败」，本轮被强行掐断。
根因：`STUCK_LOOP` 不是 DSH 的码，是本插件自己发的熔断信号（`lib/index.js` 原 406-417 行），两条判据都过松：

| 旧判据 | 缺陷 | 后果 |
|---|---|---|
| `maxSig >= 6`：最近 16 次调用里「工具名 + **参数键名集合**」≥6 次 | 指纹丢掉参数**值**，只比键名；`read{file_path,limit}` / `ops_bash{command,description}` 这类工作流天然同键 | 读 6 个文件、跑 6 条命令就熔断 |
| `fails >= 6`：最近 16 条工具结果里 ≥6 条正文含 `error|failed|失败|错误…` | 全文关键词匹配，日志正文/文档正文带这些词也算一条 | 看日志、读源码、跑构建都可能凑满 |

修复（`assessStuck` v2，已 `export` 供回归引用）：

| 新判据 | 定义 |
|---|---|
| `tailRun >= 5`（identicalRun） | 工具名 + **全参数值**（`stableJson` 递归排序后 djb2 哈希）在**尾部连续**重复 ≥5 次 |
| `errStreak >= 6`（errStreak） | 尾部**连续** ≥6 条工具结果以错误开头：`ERR|…` / `Error:` / `TypeError:` / `[exit code: N≠0]` / `"is_error": true` / `<error>` |
| 熔断条件 | 两条互不叠加，且要求 `calls >= 2`；命中才发 `finish{kind:error, failure.code:STUCK_LOOP}` |

保留 `kind:error` 的理由不变：`stop` 会被 agent loop 当成「话没说完」，实测 1044 步死循环。

回归（可重跑）：

```powershell
node D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\test-stuck-breaker.mjs   # 判据级 6 用例（v1/v2 对照）
node D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\test-stuck-e2e.mjs      # 真 stream + 本地 SSE 桩（端口 18934）
```

| 用例 | v1(旧) | v2(新) | 期望 |
|---|---|---|---|
| A 正常长任务（读6+跑6+grep4，异参同工具） | **熔断** maxSig=6 | 放行 tailRun=1 | 放行 |
| B 真空转（同参连续6次） | 熔断 | 熔断 tailRun=6 | 熔断 |
| C 连续硬报错（尾部6条 ERR\|） | 熔断 | 熔断 errStreak=6 | 熔断 |
| D 日志噪音（16条结果8条含 error 字样，全正常返回） | **熔断** fails=8 | 放行 | 放行 |
| E 同工具异值8次（edit 8 个文件） | **熔断** maxSig=8 | 放行 tailRun=1 | 放行 |
| F 偶发失败（非连续） | 放行 | 放行 | 放行 |

端到端：`normal-long-task` → `finish=stop`、正文「收到」；`true-stuck` → `finish=error`、`STUCK_LOOP` + 熔断说明文本。

可调参数（`cordis.patch.yml` 的 config 写 `stuckBreaker: {identicalRun: 8, errStreak: 8}` 覆盖默认）：

| 键 | 默认 | 含义 |
|---|---|---|
| `window` | 16 | 回看窗口（调用数 / 结果数） |
| `identicalRun` | 5 | 尾部连续同参重复次数阈值 |
| `errStreak` | 6 | 尾部连续硬报错条数阈值 |

临时全关：启动 dsh 前 `$env:NINFER_STUCK_BREAKER='off'`；或 config 里 `stuckBreaker: false`。

回滚：

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-ninfer-local\lib
Copy-Item index.js.bak-stuck1 index.js -Force      # 回到 2026-10-20 22:09 的 v1 熔断
node --check index.js
# 再 dev_reload_package packageName=dsh-ninfer-local
```

旁注：`src/adapter.ts`（15KB，2026-10-20 快照）本来就没有 `assessStuck`，本次无源码同步项；
`lib/index.js` 为运行产物真相源，重建时按本文件回填。

---

## think33 · 2026-10-27 20:0x — 修 compact 报错 `imageRequestPricing is not a function`

**现象**：GUI 里 compact 连续三次失败：
`compact · this.adapters.get(…)?adapter.imageRequestPricing is not a function`

**根因**（core 侧证据，app.asar 内 `dsh-llm` LlmRuntime）：
```js
imageRequestPricing(provider, model) {
  return this.adapters.get(provider)?.adapter.imageRequestPricing(provider, model);
}
```
可选链只保护 `adapters.get(...)` 的返回值，**不保护方法本身**。
`NinferAdapter` 未声明 `imageRequestPricing` → compact / token meter 为历史图片定价时直接 TypeError。
能力模型要求：

```ts
LlmImageRequestPrice   { visualTokens: number; text: string }
LlmImageRequestPricing { priceImages(images: readonly ImageBlock[]): readonly LlmImageRequestPrice[] }
```

附带缺陷：`imageRequestTarget(image)` 与 core 调用形态 `(provider, model, image)` 不符，命中即误用。

**改动**（lib/index.js 与 src/adapter.ts 同步）：
1. 新增 `IMAGE_PLACEHOLDER_TEXT` 常量，`blocksToText` 的 `case 'image'` 复用它（单一真相源）。
2. 新增 `textOnlyImageText(block)` / `imageAttachmentId(block)`，与 core `textOnlyImageText` 同构
   （`[image omitted because this model accepts text only; attachment sha256:<8位>]`）。
3. 补 `imageRequestPricing(provider, model)` → `{ priceImages: images => [{visualTokens:0, text}] }`。
4. `imageRequestTarget` 改为 `(providerOrImage, modelOrImage, maybeImage)` 宽容形态，尺寸缺失回落 1024。

**定价依据**：`resolveModel` 不声明 `inputModalities=image`，core 按纯文本路由处理，
出网前已把每个 image 块替换成 `textOnlyImageText`；`blocksToText` 再兜占位。
故 `visualTokens` 恒为 0（引擎无视觉 token 预算），`text` 与线上真实占位文本逐字一致。

**验证**：
- `node --check lib/index.js` → OK
- 契约探针 `_work/session-audit/probe-imgpricing.mjs`（以 profile junction + `--preserve-symlinks` 真导入）：
  `hasPricing=true`、`hasTarget=true`、两次出现均 `visualTokens=0` 且 text 到位、
  `targetCore 1441x364` / `targetLegacy 800x600` → **VERDICT PASS**
- `dev_reload_package dsh-ninfer-local` → 清缓存 1 模块、重建 1 fiber、active
- 排他：`~/.dsh/plugins/dsh-fix-imagepricing`（他人 18:50 建的 proto 兜底插件）**未被任何 profile 装配**，
  未生效，故非本次修复路径；本修复在 adapter 侧根治，不依赖它。

**路径记录**：core 补丁（把 `?.adapter.imageRequestPricing` 改成 `typeof === 'function'` 判断）
需写 `app.asar`（工作区外只读）→ 该路径不可用，改走 adapter 侧补实现，等效且可热重载。

**回滚**：
```powershell
cd D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-ninfer-local\lib
Copy-Item index.js.bak-think32 index.js -Force
node --check index.js
# dev_reload_package packageName=dsh-ninfer-local
```

**残留待办**：GUI 侧再跑一次 compact 做端到端确认（本轮已过契约探针与热重载，未跑真实压缩）。
