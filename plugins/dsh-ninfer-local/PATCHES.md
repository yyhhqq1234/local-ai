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

## think-engx1 · 2026-11-08 23:2x · 多引擎档位（9B 接入，27B 不动）

**动机**：ngineDir 单一指向 
infer-csunx（27B 专用 launcher 链）。9B 用的是自建的
_tools/ninfer-build/apps/ninfer-serve.exe + G1 三组件产物，参数语义完全不同
（--prefill-chunk 128 --no-thinking --greedy --host-context-mib 2048，无 DeviceKV/HostKVMiB 概念）。
27B 线已冻结，但不能丢：两档必须并存可切。

**改动**（lib/index.js 为运行时产物，src/engine.ts 与 src/index.ts 已同步镜像）

`
新增 ENGINE_PROFILES 档位表（默认 csunx-27b，行为逐字保留）
  csunx-27b  kind=launcher  engineDir=ninfer-csunx        modelDirs=[csunx/model, 27b/model]
  build-9b   kind=exe       exe=_tools/ninfer-build/apps/ninfer-serve.exe
                            modelDirs=[train/lines/9b-oxcoder/out]
                            defaultModel=kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer
                            maxContext=4096（引擎实际 KV 容量）
                            extraArgs=--greedy --host-context-mib 2048 --prefill-chunk 128 --no-thinking
新增 spawnExe()：直启进程（windowsHide + 日志 fd + error 监听，与 spawnEngine 同款保护）
listModels()   改为按档位汇总，每条带 profile 标签（27B 2 个 + 9B 2 个 = 4）
activeModel()  新增：按当前档位过滤，返回带绝对 path 的对象；activeModelFile() 复用它
start()        按 prof.kind 分流；launcher 分支参数与原来逐字一致（仅 -ModelFile 传文件名）
status()       新增 profile / profiles 字段；contextWindow 兼容 max_model_len（9B 引擎返回该字段）
pickParams()   接受 profile；ninfer_engine / ninfer_params 参数表补 profile
`

**验证**（_work/dsh-adapter-test/verify-profiles.mjs，独立 dir，不动 live 
infer-csunx/config）

`
默认档位           csunx-27b
模型枚举           4 个：csunx-27b ×2（9.55/9.88 GiB）· build-9b ×2（8.69/5.83 GiB）
档位隔离           csunx-27b → Huihui-...-IQ2_S-mtp.ninfer
                   build-9b  → kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer
直启 9B            start ok=true ready 7.1-7.5s  model=kittyrev-oxcoder9b-nsfw-gate-full-GSQ  ctx=4096
真实对话           content_len=43 finish=length tok=24
                   "本地推理引擎负责在用户设备上直接执行模型推理，无需联网即可提供低延迟、高隐私的 AI"
stop()             running=false（端口释放）
`

**回滚**

`powershell
cd D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-ninfer-local
Copy-Item lib\index.js.bak-engx1 lib\index.js -Force
node --check lib\index.js
`

**坑（本轮踩到并修）**

1. _tools 下目录名是 
infer-build（不是 infer-build）；exe 是 
infer-serve.exe。
   首次写档位表写成 infer-build → start() 报 ngine exe missing，已在补丁 engx1d 修正。
2. lib/index.js 用 LF，ead 工具输出也是 LF；但整块多处替换仍易断，改用「小块锚点 + 函数式
   s.replace(from, () => to)」避免 $&/$' 语义与缩进漂移。
3. 直启模式必须自带 windowsHide，否则会弹控制台窗口（操作者明确要求不弹）。

**生效条件**：lib/index.js 是运行时产物，DSH 宿主需重启（或 dev_reload_package）才加载新代码。
本插件目录没有 node_modules，无法 ash scripts/build.sh（缺 tsc），故 lib 手改、src 手镜像。

## think-engx2 · 2026-11-08 23:3x · 双引擎区分加固（27B / 9B 同名进程，按路径区分）

**背景**：本地确有两套引擎，进程名都叫 `ninfer-serve.exe`：

| 档位 | 引擎可执行 | 大小 | 启动方式 | 模型 |
|---|---|---|---|---|
| 27B | `ninfer-csunx/runtime/engine/ninfer-serve.exe` | 1.29 GB | `ninfer-csunx/run-engine.ps1`（CSUNX233 配方，KV ring/window + host-pageable） | `ninfer-27b-kv-stream-3arch-20261019/model/*.ninfer`（9.55 / 9.88 GiB） |
| 9B | `_tools/ninfer-build/apps/ninfer-serve.exe` | 262.7 MB | 直启（自建 ninfer-master 构建） | `train/lines/9b-oxcoder/out/*.ninfer`（G1 三组件 8.69 GiB / 旧 5.83 GiB） |

物理上不能同时跑（9.55 + 8.69 = 18.2 GiB > 12 GB 显存），所以仍共用 `params.port`；
但**必须能分辨谁是谁**，否则一次 stop 就会误杀另一个引擎。

**本轮改动**

```
ENGINE_PROFILES 每档新增 engineExe（真实可执行路径，用于身份识别与精准 kill）
engineInfo()    新增：返回 {profile,label,kind,exe,exists,bytes,modelDirs}
status()        新增 engine 字段（面板/工具里可直接看出当前是哪套引擎）
stop()          删除 taskkill /IM ninfer-serve.exe（会连同另一个引擎一起杀）
                改为：先按 pid 杀 → 兜底用 PowerShell 只杀 Path == 本档位 engineExe 的进程
```

**验证**（`_work/dsh-adapter-test/verify-identity.mjs`）

```
csunx-27b  exe = ninfer-csunx/runtime/engine/ninfer-serve.exe   exists=true  1,348,151,296 B
build-9b   exe = _tools/ninfer-build/apps/ninfer-serve.exe      exists=true    275,430,400 B
模型归属    csunx-27b ×2（9.55 / 9.88 GiB）· build-9b ×2（8.69 / 5.83 GiB）
起 9B      running=true profile=build-9b model=kittyrev-oxcoder9b-nsfw-gate-full-GSQ
stop()     engine answering=false；进程表 running_count=0（无残留、无误杀）
```

**回滚**

```powershell
Copy-Item lib\index.js.bak-engx2 lib\index.js -Force   # 回到含档位但不含身份加固的版本
Copy-Item lib\index.js.bak-engx1 lib\index.js -Force   # 回到单引擎版本
```

## think-engx3 · 2026-11-08 23:4x · 设置页改造（双档位 UI + 引擎身份 + 日志取最新）

**问题**：旧面板只有一套 27B 参数（池/HostKV/KV 编码/chunk/端口）+ 一个模型下拉，看不出 27B 与 9B 是两套引擎；
而且日志尾按文件名排序，会显示 2026-10-23 那次 `startup failed | missing component mtp` 的旧失败日志，误导以为当前坏着。

**改动**

```
lib/client.js（重写，198 → 约 300 行）
  新增「引擎档位」下拉（csunx-27b / build-9b）+「应用档位」按钮
  新增引擎身份行：label · kind · 可执行大小 · 完整 exe 路径（缺失时提示）
  字段按档位适用性置灰：
    deviceKV / hostKVMiB / kvDtype / draftTokens / reasoningEffort → 仅 27B
    prefillChunk / maxContext → 9B 只读（固定 128 / 4096，实测依据写在 title）
    vision / port → 两档通用
  模型下拉按当前档位过滤；切换档位即时重排
  所有请求带 profile（/params  /engine），切档位即时可见

lib/index.js
  GET /state 增加 profile / profiles / engine，models 每条带 profile
  ninfer_status 同步增加 profile / profiles / engine，modelFiles 前缀带档位
  tailLogs() 改为按 mtime 取最新文件（原来按文件名排序 → 显示 10-23 旧日志）
```

**验证**

```
node --check lib/index.js  → 0
node --check lib/client.js → 0
_state 载荷（_work/dsh-adapter-test/verify-state-payload.mjs）：
  profile=build-9b · profiles 两项 · engine.exe=.../ninfer-build/apps/ninfer-serve.exe (275,430,400 B)
  models 4 条且每条带 profile（27B x2 / 9B x2）
  logs 取到 2026-11-08 23:29 的最新 8 行（engine ready | kittyrev-... | 6.9s）
```

**生效**：client bundle 与 lib/index.js 在宿主页面/进程加载时读取，需重启 DSH 并刷新页面。

**回滚**：`Copy-Item lib\client.js.bak-engx3 lib\client.js -Force`

## think-engx4 · 2026-11-08 23:5x · 修「build-9b 会话一开就失败」的两处真因

**现象**（操作者截图，DSH 会话 Local-AI-testarea）：
```
本轮运行失败  working-directory: directory does not exist:
              "D:\BaiduNetdiskDownload\Local-AI\Local-AI-testarea"
（底部模型选择器显示 Qwen3.8-27B 无审查 · IQ2_S · MTP）
```

**真因 1：会话工作目录不存在**（与引擎无关）
```
D:\BaiduNetdiskDownload\Local-AI\Local-AI-testarea  → Test-Path = False
修：New-Item -ItemType Directory -Force 建出该目录（已建，Test-Path=True）
```

**真因 2：模型下拉硬给了 27B 兜底 id**
```
引擎没起时 listModels() 直接返回 profile.fallbackModels（写死 qwen3.8-27b-ablit-swift15-iq2s）
而 9B 引擎只认 kittyrev-oxcoder9b-nsfw-gate-full-GSQ
实测：POST /v1/chat/completions model=kittyrev-...GSQ → 200 OK
      POST /v1/chat/completions model=qwen3.8-27b-ablit-swift15-iq2s → 404 model_not_found
```

**改动**
```
lib/index.js  listModels()：引擎在跑且返回非空 → 一律用引擎的 id 列表；
              引擎没起 → 返回「当前档位的现行模型」（manager.activeModelFile() 去掉 .ninfer），
              不再落回硬编码 fallbackModels
lib/index.js  apply(): 给 adapter 传 activeModelId 回调（闭包读 manager）
```

**验证**（_work/dsh-adapter-test/verify-model-id.mjs）
```
csunx-27b → activeModelId = Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp
build-9b  → activeModelId = kittyrev-oxcoder9b-nsfw-gate-full-GSQ
端口 1234 实跑引擎 /v1/models → id=kittyrev-oxcoder9b-nsfw-gate-full-GSQ, max_model_len=4096
node --check lib/index.js → 0
```

**回滚**：`Copy-Item lib\index.js.bak-engx4 lib\index.js -Force`

## think-engx5 · 2026-11-09 00:0x · 模型下拉列全量（27B+9B）+ 两档都支持思考档位

**需求**：模型选择里 9B 与 27B 都要出现；两档都要能选思考强度。

**实测前提**（先验证再改代码）
```
9B 引擎接受 reasoning_effort / enable_thinking / thinking_budget（均 200，不报错）
9B 去掉 --no-thinking 重新起（同模型、端口 1652）：
  plain                → content=49 reasoning=0 tok=31「梯度下降是…」✅ 正文正常
  reasoning_effort=high→ content=49 reasoning=0 tok=31 ✅ 不报错
  enable_thinking=false→ content=43 reasoning=0 tok=27 ✅ 被引擎尊重
⇒ 结论：9B 不必永久 --no-thinking；短问题即便开思考也不会把正文吃空
```

**改动**
```
lib/index.js
  listModels()  合并「本地模型目录（27B+9B 全量）」+「引擎正在跑的 id（置顶）」
                → 选择器永远能看到 4 个模型，不再只显示当前引擎那一个
  apply()       新增 modelCatalog()（给每个模型名后缀档位标签 + 体积）
                新增 ensureModel(modelId)：选中的模型与当前引擎不一致 → 切档位/模型并重启；
                已一致且没跑 → 拉起；不在目录里（引擎自报名）→ 不动
  stream()      请求前 await ensureModel(options.model)
  effort        除 body.reasoning_effort 外，再发 chat_template_kwargs.enable_thinking = (eff !== none)
  build-9b 启动 --no-thinking 改为条件：仅当 reasoningEffort === none 时加
                （其余档位保留思考通道，由 enable_thinking 逐请求控制）

lib/client.js
  模型下拉不再按档位过滤 → [27B]/[9B] 标签 + 文件名 + 体积，一次看全
  选模型时自动同步「引擎档位」下拉（按 option 的 data-p）
  思考强度字段从「仅 27B」改为两档通用
```

**验证**
```
node --check lib/index.js  → 0
node --check lib/client.js → 0
目录全量 = 4：
  [27B] Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp  9.55 GiB
  [9B ] kittyrev-oxcoder9b-nsfw-gate-full-GSQ                        8.69 GiB
  [9B ] oxcoder9b-merged                                             5.83 GiB
  [27B] qwen3.8-27b-kittyrev-v6-iq2s-mtp                             9.88 GiB
端口 1234 在跑：["kittyrev-oxcoder9b-nsfw-gate-full-GSQ"]
```

**注意**：选到另一档的模型时，首次请求会触发一次引擎重启（27B 冷启较慢）。

**回滚**：`Copy-Item lib\index.js.bak-engx5 lib\index.js -Force`

## think-engx7 · 2026-11-09 00:2x · 9B 上下文从 4096 → 16384 + prompt 预算裁剪（修 context_length_exceeded）

**现象**：DSH 里发「你好」→ `ninfer 400 context_length_exceeded: prepared prompt exceeds Engine max_context 4096`。

**实测定位**
```
DSH 实际请求体量（_work/session-audit/ninfer-stats.jsonl）：
  model=kittyrev-...GSQ tools=14 systemChars=35398 totalChars=54284 payload=66KB
  ⇒ 约 2 万 token，4096 窗口装不下
tokenizer 实测比（同一引擎，读日志 prompt N）：
  中文 1700 字 → 1012 tok（1.68 字/token）
  英文 3540 字 →  672 tok（5.27 字/token）
  混合 3960 字 → 1632 tok（2.43 字/token）
上下文上限实测（阶梯，--max-context 16384）：
  24000 字(14727 tok)+512 out → 200 ✅
  规则：prompt_tokens + max_tokens ≤ max_context
显存实测（9B 8.69 GiB 权重，12 GB 卡）：
  4096  → KV 64 pages  / 242 MiB / free 2.63 GiB
  16384 → KV 256 pages / 626 MiB / free 2.76 GiB  ✅ 选用
  16384 + --vision → KV runtime 1.41 GiB / free 1.12 GiB（vision 吃约 800 MiB）
  32768 → free 0 B、启动 1m58s、主机内存被撑满（爆内存）  ❌ 禁用
  65536 → FATAL Device budget cannot hold model weights  ❌
```

**改动**
```
lib/index.js  build-9b profile: maxContext 4096 → 16384
              新增 contextBudget { window: 16384, maxOutput: 2048, reserve: 512 }
              apply(): contextBudget 以函数形式随当前档位动态取
              stream(): 发送前按预算裁剪
                - system 自身超预算 → 保留头 60% + 尾 40%，中间插截断标记（压到预算 85%）
                - 其余消息从最新往回填，超出的旧消息丢弃并插一条说明
                - max_tokens 压到 min(请求值, 2048)
_tools/run-serve.ps1  $MaxContext 4096 → 16384
```

**踩到的 bug（已修）**：裁剪只回写了「有消息被丢弃」的分支，system 被压缩但没丢消息时不生效，
导致 body 仍是原始 25200 字符 → 依旧 400。改为无条件回写 messages。

**验证**
```
node --check lib/index.js → 0
ladder：4000/12000/16000/20000/24000 字 prompt + 512 out 全 200
DSH 体量复刻（system 25200 字 + 你好，max_tokens 2048）：
  修前 400 context_length_exceeded；修后 200（system 压到 ≈11785 tokens）
引擎当前（1234）：--max-context 16384，KV 256 pages / 626 MiB / free 2.76 GiB / ready 8s
```

**代价**：9B 会话的 system prompt 会被压掉约一半（DSH 约定段实测 35K 字符），
长对话的早期消息会被丢弃。需要完整约定/长上下文时改用 27B（262144）。

**回滚**：`Copy-Item lib\index.js.bak-engx6 lib\index.js -Force`

## think-engx10 · 2026-11-09 01:0x · 9B 退化根因定性（负结果）：system 角色 / 多轮结构不可用

**现象**：DSH 里 9B 输出乱码（随机拉丁串、URL 片段）。

**排除项（逐项实测，同一产物 kittyrev-oxcoder9b-nsfw-gate-full-GSQ）**
```
max-context 4096 vs 16384      → 输出逐字相同，与上下文大小无关
关思考 vs 开思考               → 都是乱码
prefill-chunk 120/112/96       → 引擎起不来（只接受 16 的倍数：64/128/256…）
chat-template 换成外部 jinja   → 与自带模板逐字相同，模板不是变量
G1 产物 vs Q4Q5 产物           → 两代都乱码，不是 G1 转换的问题
temperature 0 / 0.3 / 0.7+topP → 都乱码，不是 greedy 坍缩
system 压缩到 32 字符          → 仍乱码，不是"system 太长"
```

**决定性对照（唯一变量 = 消息结构）**
```
[user-only]  "用中文一句话回答：1+1 等于几？"  → "1+1 等于 2。"        ✅ 稳定
[system+user] "你是助手，中文简短。"+同一问题   → "<.TO_LOL_jpDFULL,..." ❌
[merged]      设定并进同一条 user            → 仍然乱码             ❌
[multi-turn]  user/assistant/user 无 system  → 乱码                 ❌
```

**结论**：该引擎对 9B 产物的 `system` 角色与多轮消息结构的模板化是坏的
（不是模型能力问题：单条 user 消息稳定正确）。DSH 每轮必带 system + 多轮，
所以在引擎侧修好之前，9B 无法用于 DSH 会话。

**本轮同时修掉的 adapt​er bug**（保留，仍然有用）
```
trimToBudget 无裁剪时返回同一数组引用 → 回写时"清空再遍历自身" → messages 变空 → 400
  修法：early return 返回 messages.slice()；回写前再判一眼引用
  证据：修前 [dbg] messages.length=0；修后 =2 / =4 正常发出
```

**当前 9B 的可用范围**：单条 user 短问答（accept_final 5×3=15/15 就属于这一类）。

**回滚**：`Copy-Item lib\index.js.bak-engx9 lib\index.js -Force`

## think-engx11 · 2026-11-09 01:3x · 27B / 9B 引擎一一对应（禁止跨引擎混用）

**操作者约束**：27B 与 9B 的引擎必须一一对应，不能混着用。

**配对表（硬编码在档位里，代码层面校验）**
```
27B → csunx 引擎：ninfer-csunx/runtime/engine/ninfer-serve.exe
      模型目录：ninfer-csunx/model · ninfer-27b-kv-stream-3arch-20261019/model
9B  → 自建引擎：_tools/ninfer-build/apps/ninfer-serve.exe
      模型目录：train/lines/9b-oxcoder/out
```

**本轮改动**
```
lib/index.js  start()：模型必须落在本档位 modelDirs 内，否则抛错（不再"随便拿个模型喂给当前引擎"）
              ensureModel()：请求的模型若属于另一个档位 → 直接拒绝并提示先切档位，
                             不再自动改 profile + 重启（那等于跨引擎调度）
              （stop() 已在 engx2 改为只杀本档位 exe，不会误杀另一台引擎）
src/engine.ts  同步镜像 start() 的目录校验
```

**为什么这样定**：实测两套引擎能力集不重叠，混用必失败——
```
27B 产物 + 自建引擎 → FATAL weight/000184: unknown tensor layout: gguf_blocks_v1
9B 产物 + csunx 引擎 → FATAL text/layers/0: input projection: unsupported logical projection geometry
```

**验证**：node --check lib/index.js = 0；两处守卫静态命中（L349/L1395 附近）。

**回滚**：`Copy-Item lib\index.js.bak-engx11 lib\index.js -Force`

## think-engx12 · 2026-11-11 11:15–12:20 · 9B 文本工具调用 shim（tool_calls 通道打通）

**问题（实测）**：9B 的 SFT 语料是文本形态（`kitty_ce op=AL_DEL|<index>`），
三组对照（训练格式 system / 强约束 JSON / OpenAI tools）都不产结构化 `tool_calls`
（`tool_calls=null|{}`，无 `<tool_call>` 标记）→ DSH agent loop 拿不到可执行调用，只能聊。

**本轮改动（只加不删；27B 档位零影响）**
```
lib/index.js
  ENGINE_PROFILES['build-9b']  + textToolCalls: true          # 只有 9B 开
  textToolProtocol()           新增：注入 system 尾部的调用协议（带工具名清单）
  parseTextToolCall()          新增（export，便于单测）：四种确定性形态
     1 <tool_call>{"name","arguments"}</tool_call>
     2 ```json {"name","arguments"} ```
     3 裸 JSON 行 {"name","arguments"} / {"op":"read",...}（op 当工具名，SFT 泄漏形态）
     4 kitty_ce op=MODENUM（SFT 原生文本形态）
     工具名不在白名单/参数不是对象 → 返回 null（绝不猜，不执行编造的工具名）
  stream()  + profileFlags 读取（按当前档位动态取，不写进 config）
            + 协议注入放在 compactSystem / trimToBudget 之后（否则会被 compact 重建 system 时丢掉）
            + holdText：正文可能整段就是标记 → 首字符是 < ` { 时先压住，确认是正文立刻放行
            + 收尾把标记转成 tool-call 块（block-end 带剥掉标记的正文），并补一条 tool-call-delta
            + kind 优先级修正：toolCalls.size>0 一律 tool-calls（9B 常在调用行后继续写正文撞 max_tokens，
              按 length 收口会让 DSH 当"被截断的纯文本"，工具不执行）
  apply()   + profileFlags: () => ({ textToolCalls: ENGINE_PROFILES[当前档位].textToolCalls === true })
lib/index.js.bak-engx12      本轮基线备份
```

**关键发现（引擎侧，非适配器）**：引擎自身就能解析 `<tool_call>{"name":..,"arguments":..}</tool_call>`
并直接下发 OpenAI 形态的 `tool_calls` delta（实测 HTTP 200，`tool_calls[{name:"read",arguments:"{\"path\":\"README.md\",\"limit\":20}"}]`）。
所以 shim 的主要作用是**协议注入**（教会模型发这个标记），解析器只是兜底。

**验证（可复现）**
```
node --check lib/index.js                                → 0
node _work\ninfer-9b\shim-unit.mjs                       → 11/11 pass（四种形态 + 白名单拒绝 + 不误判）
node _work\ninfer-9b\p3_adapter_shim_e2e.mjs             → 3/3 pass（走适配器真实 stream()）
  T1 工具任务：finish=tool-calls，read{"path":"README.md","limit":20}
  T2 普通问答：finish=max-tokens，正文 80 tok，无 tool-call（不误判）
  T3 kitty 任务：finish=tool-calls，kitty_ce{"op":"R|0xMODENUM|dword"}
```

**已知残留**
```
· 9B 复读：一次可能连发 3 条相同调用（T1 实测 3×read）→ DSH 会重复执行同一读取；
  protocol 已写"一次只发一个"，模型仍偶发。去重会破坏 delta/block-end 配对，暂不做。
· 模型仍会偶发凭记忆编造（未调用工具就写内存值/文件内容）→ 属模型能力，非 shim 问题。
```

**生效方式（重要）**：`dev_reload_package dsh-ninfer-local` 会把 DSH 卡死（实测两次：工具消失 / 整个 web 无响应）。
**必须用重启 DSH 的方式加载新代码。**

**回滚**：`Copy-Item lib\index.js.bak-engx12 lib\index.js -Force` 然后重启 DSH。

### think-engx12 补录 · 2026-11-11 21:3x · 真实形态两处修正（长 system / 协议措辞 / 去重）

**1) 9B 必须开极简 system（本来就在档位里，但 live 配置没把它传进适配器）**
```
实测（p3_ctx_matrix.py，同任务/同 14 工具，只看 system 长度）：
  短 system(210 字符) + 3 工具   → calls=3
  短 system(210 字符) + 14 工具  → calls=4   （工具数量不是变量）
  长 system(6541 字符) + 3 工具  → calls=0   （直接改写成编造的 README）
  长 system(6541 字符) + 14 工具 → calls=0
修法：profileFlags 里补 compactSystem / compactSystemText / compactHistoryMessages，
      stream() 用 `this.profile.compactSystem || profileFlags.compactSystem` 判定。
DSH 真实 system 是 35,398 字符 → 不压必然全丢工具能力。
```

**2) 协议措辞：不能写"禁止凭记忆编造文件内容/内存数值"**
```
p3_proto_ab.py（同任务/同 14 工具，只换措辞）：
  含"禁止编造文件内容"句 → calls=0（模型转而直接写 README 内容）
  只讲格式/粒度（3 名单/14 名单/显式示例/极简一行）→ calls=3 / 4 / 4 / 4
 ⇒ 协议只描述输出格式与粒度，不写"不要编造"。
   同时撤掉 user 尾部提醒（同样的措辞副作用）。
```

**3) 工具 delta 缓冲 + 同参调用去重**
```
9B 一轮会连发 2–4 条相同调用（实测 3×read），重复的 ops_bash 会被执行两遍。
textToolCalls 档位：tool-call-delta 先缓冲、收尾按 name|arguments 去重，再统一补 delta + block-end。
非 9B 档位保持原样（流式 delta 不变）。
```

**验证（重启 DSH 后跑）**
```
node _work\ninfer-9b\shim-unit.mjs                 → 11/11
node _work\ninfer-9b\p3_adapter_shim_e2e.mjs       → 3/3（T1 read / T2 不误判 / T3 两条 kitty_ce）
node _work\ninfer-9b\p3_realshape_probe.mjs        → 2/2（8660 字符 system + 14 工具，压到 32 字符后仍能发调用）
```

## think-llamacpp · 2026-11-12 08:40 · 新增外部档 llama-cpp（llama.cpp/Ollama 端点）

**动机**：实测同机同模型，llama.cpp Q4_K_M 中位 98.75 tok/s、17/17 回归、**原生 tool_calls**；
自研 ninfer 35.4–36.2 tok/s 且不产结构化调用。

**改动（lib/index.js，备份 lib/index.js.bak-llamacpp）**
```
ENGINE_PROFILES['llama-cpp']  新增：kind='external'、baseURL=http://127.0.0.1:11434/v1、
                              defaultModel='kittyrev9b-q4km'、textToolCalls=false、compactSystem=false
status()      baseURL 取 prof.baseURL（外部档）否则按 port 拼
start()       外部档不 spawn，直接报"端点未就绪"（提示启动 ollama/llama-server）
stop()        外部档直接返回，不杀进程
listModels()  外部档补一条 defaultModel 伪目录项，供模型选择器显示
NinferAdapter.baseUrl()  新增：优先 profileBaseUrl()（apply 里按当前档位动态返回）
              /models 与 /chat/completions 三处改用 this.baseUrl()
apply()       + profileBaseUrl: 返回 ENGINE_PROFILES[当前档位].baseURL
```
**验证**
```
node --check = 0
node _work\ninfer-9b\p3_llamacpp_adapter_test.mjs
→ tool_calls=[{name:"read",args:"{\"path\":\"README.md\"}"}]，finish=tool-calls，wall 581 ms  ✅
（走的是适配器真实 stream()，请求被 profileBaseUrl 正确转发到 :11434）
```
**生效**：需重启 DSH（dev_reload_package 会卡死）。切换档位：ninfer_params set profile=llama-cpp
**回滚**：Copy-Item lib\index.js.bak-llamacpp lib\index.js -Force
**不影响**：csunx-27b / build-9b 两档行为不变（新增键只在 llama-cpp 档出现）
