/**
 * NinferAdapter —— 把本地 NInfer 引擎（OpenAI 兼容 /v1/chat/completions）接进 DSH 的 llm seam。
 *
 * 职责边界：
 * - 路由：一个 provider 路由 = 一个 baseURL（默认 ninfer → 127.0.0.1:1234/v1）
 * - 模型：模型清单来自引擎的 /v1/models（含 context_window / meta），也允许配置兜底
 * - 流：OpenAI SSE → DSH StreamChunk（text-delta / reasoning-delta / tool-call-delta / usage / finish）
 *
 * 不做：重试（交给 dsh-llm-retry）、凭据管理（本地引擎无鉴权）、图片真实上传（视觉走引擎侧 CPU 路径，
 * 请求里以文本占位，避免把 base64 灌进 12G 卡的上下文）。
 */
import { LlmAdapter } from '@deepseek-ai/dsh-llm'
import { appendFileSync } from 'node:fs'
import type {
  GenerateOptions,
  LlmModelInfo,
  LlmResolvedModelInfo,
  PreparedAdapterCall,
  StreamChunk,
  AssistantMessage,
  ToolSchema,
  ContentBlock,
} from '@deepseek-ai/dsh-llm'

export interface NinferProfile {
  /** OpenAI 兼容基址，含 /v1 */
  baseURL: string
  displayName: string
  /** 引擎未启动时的兜底模型目录 */
  fallbackModels?: Array<{ id: string; name: string; contextWindow: number; maxTokens?: number }>
  /** 单次请求超时（ms），本地大模型冷 prefill 可能很慢 */
  timeoutMs?: number
  /** 是否把 reasoning_content 作为 reasoning 块回传 */
  emitReasoning?: boolean
  /**
   * 工具白名单（只作用于本 provider 的请求，云端路由不受影响）。
   * 精确名或前缀通配（`mcp__godot-ai__*`）。空数组/未设 = 不裁剪。
   * 动机：238 个工具 schema ≈ 67K tokens，是本地 12G 卡冷 prefill 首字慢的主因。
   */
  toolAllowlist?: string[]
  /** 折叠 system 里的 <available_skills> 段为「技能名一行」（省 ≈19K tokens）；默认 true */
  slimSkills?: boolean
  /** 默认思考强度（模型选择器初始值）。本地 IQ2 量化模型默认 minimal 防长思考烧预算 */
  defaultEffort?: string
  /** 每次请求的 payload 体积统计追加写到该文件（ASCII 路径）；不设则不写 */
  statsPath?: string
}

interface OpenAITool {
  type: 'function'
  function: { name: string; description?: string; parameters?: Record<string, unknown> }
}

interface OpenAIMessage {
  role: 'system' | 'user' | 'assistant' | 'tool'
  content: string | Array<{ type: string; text?: string; image_url?: { url: string } }> | null
  tool_calls?: Array<{ id: string; type: 'function'; function: { name: string; arguments: string } }>
  tool_call_id?: string
}

/** 图片在 ninfer 路由上的唯一占位文本（blocksToText 与 imageRequestPricing 共用；运行时以 lib 为准） */
const IMAGE_PLACEHOLDER_TEXT = '[图片：本机视觉为 CPU 路径，历史图片不回灌]'

/** 与 core textOnlyImageText 同构：text-only 路由出网前会把 image 块替换成该文本 */
function imageAttachmentId(block: unknown): string {
  const ref = (((block as { attachment?: unknown } | null)?.attachment ?? block ?? {}) as {
    attachmentId?: string
    sha256?: string
    id?: string
  })
  const raw = String(ref.attachmentId ?? ref.sha256 ?? ref.id ?? '')
  return raw.startsWith('sha256:') ? raw.slice(7) : raw
}

function textOnlyImageText(block: unknown): string {
  return `[image omitted because this model accepts text only; attachment sha256:${imageAttachmentId(block).slice(0, 8)}]`
}

/** DSH content blocks → 纯文本（图片走占位，避免 12G 卡被图像 token 挤爆） */
function blocksToText(blocks: readonly ContentBlock[]): string {
  const out: string[] = []
  for (const b of blocks) {
    switch (b.type) {
      case 'text':
        out.push(b.text)
        break
      case 'reasoning':
        // 历史里的思考不回灌给模型，避免污染上下文
        break
      case 'image':
        out.push(IMAGE_PLACEHOLDER_TEXT)
        break
      case 'file':
        out.push(`[文件附件 ${b.attachment.name}，${b.attachment.bytes} 字节，内容未内联]`)
        break
      case 'tool-call':
        break
      case 'tool-addition':
      case 'tool-removal':
        break
    }
  }
  return out.join('\n')
}

function toOpenAIMessages(options: GenerateOptions): OpenAIMessage[] {
  const msgs: OpenAIMessage[] = []
  if (options.system) msgs.push({ role: 'system', content: options.system })
  for (const m of options.messages) {
    switch (m.role) {
      case 'system':
      case 'developer':
        msgs.push({ role: 'system', content: blocksToText(m.content) })
        break
      case 'user':
        msgs.push({ role: 'user', content: blocksToText(m.content) })
        break
      case 'assistant': {
        const asst = m as AssistantMessage
        const text = blocksToText(asst.content)
        const calls = asst.content.filter((b) => b.type === 'tool-call') as Array<Extract<ContentBlock, { type: 'tool-call' }>>
        const msg: OpenAIMessage = { role: 'assistant', content: text || null }
        if (calls.length) {
          msg.tool_calls = calls.map((c) => ({
            id: c.id,
            type: 'function' as const,
            function: { name: c.name, arguments: c.arguments },
          }))
        }
        msgs.push(msg)
        break
      }
      case 'tool':
        msgs.push({
          role: 'tool',
          tool_call_id: String(m.toolCallId),
          content: blocksToText(m.content),
        })
        break
    }
  }
  return msgs
}

function toOpenAITools(tools: readonly ToolSchema[] | undefined): OpenAITool[] | undefined {
  if (!tools?.length) return undefined
  return tools.map((t) => ({
    type: 'function' as const,
    function: {
      name: t.name,
      description: t.description,
      parameters: (t.parameters ?? { type: 'object', properties: {} }) as Record<string, unknown>,
    },
  }))
}

/** 白名单匹配：精确名，或 `前缀*` 通配。 */
function matchAllow(name: string, allow: readonly string[]): boolean {
  for (const rule of allow) {
    if (rule.endsWith('*')) {
      if (name.startsWith(rule.slice(0, -1))) return true
    } else if (name === rule) return true
  }
  return false
}

/**
 * 只对本 provider 生效的工具裁剪：238 个 schema 缩到白名单，冷 prefill 从 ≈67K tokens 降到 ≈5K。
 * 云端 provider（commandcode / nvidia / deepseek）走各自的 adapter，不受这里影响。
 */
function filterTools(tools: readonly ToolSchema[] | undefined, allow?: readonly string[]): readonly ToolSchema[] | undefined {
  if (!tools?.length || !allow?.length) return tools
  const kept = tools.filter((t) => matchAllow(t.name, allow))
  return kept.length ? kept : tools
}

/**
 * 折叠 <available_skills> 段：只留技能名，砍掉每条 1-2 行的描述。
 * DSH 的 skills 目录清单 ≈75K 字符/19K tokens，本地模型承担不起冷 prefill。
 * 技能仍可经 `skill` 工具按名加载，不影响可用性。
 */
export function slimSkillsBlock(system: string): string {
  return system.replace(/<available_skills>([\s\S]*?)<\/available_skills>/g, (whole, body: string) => {
    const names = [...body.matchAll(/^- `([^`]+)`/gm)].map((m) => m[1])
    if (!names.length) return whole
    const head = `- 可用技能（${names.length} 个，按需用 skill 工具加载；描述已省略以省前缀）：`
    const list = names.map((n) => `  \`${n}\``).join(' · ')
    return `${head}\n${list}\n`
  })
}

/** 解析 SSE：逐行 data: {...} */
async function* sseLines(res: Response, signal?: AbortSignal): AsyncGenerator<string> {
  const reader = res.body?.getReader()
  if (!reader) throw new Error('ninfer: response has no body')
  const decoder = new TextDecoder()
  let buf = ''
  try {
    while (true) {
      if (signal?.aborted) throw new Error('aborted')
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx).replace(/\r$/, '')
        buf = buf.slice(idx + 1)
        if (line.startsWith('data:')) yield line.slice(5).trim()
      }
    }
    if (buf.startsWith('data:')) yield buf.slice(5).trim()
  } finally {
    reader.releaseLock?.()
  }
}

export class NinferAdapter extends LlmAdapter {
  private readonly profile: NinferProfile

  constructor(profile: NinferProfile) {
    super()
    this.profile = profile
  }

  override providerInfo(provider: string) {
    return { id: provider, name: this.profile.displayName }
  }

  /** core 调用形态 (provider, model, image)；尺寸缺失时回落到 1024 保守值 */
  override imageRequestTarget(
    _provider: string,
    _model: string,
    image: { width?: number; height?: number; mediaType?: string },
  ) {
    const w = Math.trunc(Number(image?.width))
    const h = Math.trunc(Number(image?.height))
    return {
      width: w > 0 ? w : 1024,
      height: h > 0 ? h : 1024,
      maxBytes: 4 * 1024 * 1024,
    }
  }

  /**
   * 请求图片定价。core LlmService.imageRequestPricing(provider, model) 同步取用，
   * 缺此方法会在 compact / token meter 直接 TypeError。
   * ninfer 的 resolveModel 不声明 inputModalities=image → core 按纯文本路由把 image 块
   * 替换为 textOnlyImageText；本适配器 blocksToText 再兜占位。故 visualTokens 恒为 0。
   */
  override imageRequestPricing(_provider: string, _model: string) {
    const visionCapable = (this.profile as { visionCapable?: boolean }).visionCapable === true
    return {
      priceImages: (images: readonly unknown[]) =>
        (Array.isArray(images) ? images : []).map((block) => ({
          visualTokens: 0,
          text: visionCapable ? IMAGE_PLACEHOLDER_TEXT : textOnlyImageText(block),
        })),
    }
  }

  override async listModels(_provider: string): Promise<readonly LlmModelInfo[]> {
    try {
      const r = await fetch(`${this.profile.baseURL}/models`, {
        signal: AbortSignal.timeout(this.profile.timeoutMs ?? 5000),
      })
      const d = (await r.json()) as { data?: Array<{ id: string; context_window?: number; meta?: { n_ctx?: number } }> }
      return (d.data ?? []).map((m) => ({ provider: _provider, id: m.id, name: m.id }))
    } catch {
      return (this.profile.fallbackModels ?? []).map((m) => ({ provider: _provider, id: m.id, name: m.name }))
    }
  }

  override async resolveModel(provider: string, model: string): Promise<LlmResolvedModelInfo> {
    const fallback = this.profile.fallbackModels?.find((m) => m.id === model)
    try {
      const r = await fetch(`${this.profile.baseURL}/models`, {
        signal: AbortSignal.timeout(this.profile.timeoutMs ?? 5000),
      })
      const d = (await r.json()) as {
        data?: Array<{ id: string; context_window?: number; meta?: { n_ctx?: number; n_ctx_train?: number } }>
      }
      const hit = (d.data ?? []).find((m) => m.id === model) ?? d.data?.[0]
      const ctx = Number(hit?.context_window ?? hit?.meta?.n_ctx ?? hit?.meta?.n_ctx_train ?? 0)
      return {
        provider,
        id: model,
        name: model,
        context: ctx > 0 ? { contextWindow: ctx } : undefined,
        defaultMaxTokens: 8192,
        reasoning: {
          efforts: [
            { id: 'none' as never, name: 'none' },
            { id: 'minimal' as never, name: 'minimal' },
            { id: 'low' as never, name: 'low' },
            { id: 'medium' as never, name: 'medium' },
            { id: 'high' as never, name: 'high' },
            { id: 'xhigh' as never, name: 'xhigh' },
          ],
          defaultEffort: (this.profile.defaultEffort ?? 'minimal') as never,
        },
      }
    } catch {
      return {
        provider,
        id: model,
        name: fallback?.name ?? model,
        context: { contextWindow: fallback?.contextWindow ?? 262144 },
        defaultMaxTokens: fallback?.maxTokens ?? 8192,
      }
    }
  }

  override async prepareCall(provider: string, model: string): Promise<PreparedAdapterCall> {
    const info = await this.resolveModel(provider, model)
    return {
      model: info,
      stream: (options) => this.stream(options),
    }
  }

  override async *stream(options: GenerateOptions): AsyncIterable<StreamChunk> {
    const messages = toOpenAIMessages(options)
    if (this.profile.slimSkills !== false) {
      for (const m of messages) {
        if (m.role === 'system' && typeof m.content === 'string') m.content = slimSkillsBlock(m.content)
      }
    }
    const body: Record<string, unknown> = {
      model: options.model,
      messages,
      stream: true,
      temperature: options.temperature,
      max_tokens: options.maxTokens,
      stop: options.stop,
    }
    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))
    if (tools) body.tools = tools
    if (options.reasoningEffort) body.reasoning_effort = String(options.reasoningEffort)
    if (this.profile.statsPath) {
      try {
        const systemChars = messages.reduce((a, m) => a + (m.role === 'system' && typeof m.content === 'string' ? m.content.length : 0), 0)
        appendFileSync(this.profile.statsPath, JSON.stringify({
          ts: Date.now(), model: options.model, tools: tools?.length ?? 0,
          systemChars, payloadBytes: JSON.stringify(body).length,
        }) + '\n')
      } catch {
        // 统计失败不影响主链路
      }
    }

    const res = await fetch(`${this.profile.baseURL}/chat/completions`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      signal: options.signal,
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '')
      yield {
        type: 'finish',
        reason: {
          kind: 'error',
          failure: { message: `ninfer ${res.status}: ${text.slice(0, 400)}`, code: 'NINFER_HTTP', status: res.status },
        },
      }
      return
    }

    let textIndex = 0
    let reasoningIndex = -1
    let textStarted = false
    let reasoningStarted = false
    const toolBuffers = new Map<string, { name: string; args: string }>()
    let finishReason: 'stop' | 'length' | 'tool_calls' | 'error' = 'stop'
    let usage: Record<string, number> | undefined

    for await (const raw of sseLines(res as unknown as Response, options.signal)) {
      if (!raw || raw === '[DONE]') continue
      let chunk: any
      try { chunk = JSON.parse(raw) } catch { continue }
      if (chunk.usage) usage = chunk.usage
      const choice = chunk.choices?.[0]
      if (!choice) continue
      const delta = choice.delta ?? {}

      // 思考通道
      const reasoningDelta: string | undefined = delta.reasoning_content ?? delta.reasoning
      if (this.profile.emitReasoning !== false && reasoningDelta) {
        if (!reasoningStarted) {
          reasoningStarted = true
          reasoningIndex = textStarted ? 1 : 0
          yield { type: 'block-start', index: reasoningIndex, blockType: 'reasoning' }
        }
        yield { type: 'reasoning-delta', index: reasoningIndex, text: reasoningDelta }
      }

      // 正文
      if (typeof delta.content === 'string' && delta.content.length) {
        if (reasoningStarted && !textStarted) {
          yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: '' } }
        }
        if (!textStarted) {
          textStarted = true
          textIndex = reasoningStarted ? 1 : 0
          yield { type: 'block-start', index: textIndex, blockType: 'text' }
        }
        yield { type: 'text-delta', index: textIndex, text: delta.content }
      }

      // 工具调用
      if (Array.isArray(delta.tool_calls)) {
        for (const tc of delta.tool_calls) {
          const id = String(tc.id ?? tc.index ?? 0)
          const cur = toolBuffers.get(id) ?? { name: '', args: '' }
          if (tc.function?.name) cur.name = tc.function.name
          if (tc.function?.arguments) cur.args += tc.function.arguments
          toolBuffers.set(id, cur)
          yield {
            type: 'tool-call-delta',
            id: id as never,
            name: cur.name || undefined,
            argumentsDelta: tc.function?.arguments ?? '',
          }
        }
      }

      if (choice.finish_reason) {
        finishReason = choice.finish_reason === 'length'
          ? 'length'
          : choice.finish_reason === 'tool_calls' ? 'tool_calls' : 'stop'
      }
    }

    if (textStarted) {
      yield { type: 'block-end', index: textIndex, block: { type: 'text', text: '' } }
    }
    if (usage) {
      yield {
        type: 'usage',
        usage: {
          inputTokens: Number(usage.prompt_tokens ?? 0),
          outputTokens: Number(usage.completion_tokens ?? 0),
          totalTokens: Number(usage.total_tokens ?? 0),
          reasoningTokens: Number(usage.completion_tokens_details?.reasoning_tokens ?? 0) || undefined,
          cacheReadTokens: Number(usage.prompt_tokens_details?.cached_tokens ?? 0) || undefined,
        },
      }
    }

    const kind = finishReason === 'length' ? 'max-tokens'
      : finishReason === 'tool_calls' || toolBuffers.size > 0 ? 'tool-calls'
        : 'stop'
    yield { type: 'finish', reason: { kind } as never }
  }
}
