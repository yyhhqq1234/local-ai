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
