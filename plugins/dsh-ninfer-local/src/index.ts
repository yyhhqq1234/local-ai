/**
 * @dsh-external/dsh-ninfer-local —— NInfer 本地模型后端。
 *
 * 两件事合一：
 * 1) 模型后端：向 ctx.llm 注册 `ninfer` 适配器路由（OpenAI 兼容，默认 127.0.0.1:1234）。
 * 2) 运维面：4 个工具管理引擎进程、模型切换、关键参数（思考强度/上下文/页池/KV 编码/视觉）。
 *
 * 资源注册全部挂 ctx.effect —— fiber dispose 时自动注销 provider 与工具。
 *
 * 工具契约：parameters 用「字段映射」形态声明
 *   { 字段名: { type: 'string'|'number'|'boolean', required?: true, description?, enum? } }
 * 必须投影成根为 object 的 provider 侧 JSON Schema。运行时（lib 产物）不解析
 * @deepseek-ai/dsh-tools —— 本插件目录没有 node_modules，裸导入会 ERR_MODULE_NOT_FOUND，
 * 故由下方 tool()/paramSchema() 就地完成与 parameterSchemaSpecToJsonSchema 同规则的投影。
 */
import type { Context } from 'cordis'
import z from 'schemastery'
import { NinferAdapter, type NinferProfile } from './adapter.js'
import { DEFAULT_PARAMS, NinferManager, type EngineParams } from './engine.js'

export const name = '@dsh-external/dsh-ninfer-local'
export const inject = ['llm', 'tools']

export interface Config {
  /** provider 路由名（在模型选择器里显示为 <provider>/<model>） */
  provider: string
  displayName: string
  /** OpenAI 兼容基址（含 /v1） */
  baseURL: string
  /** NInfer 发行目录（含 run-engine.ps1、model/、logs/） */
  engineDir: string
  /** 插件加载时如果引擎没起，是否自动拉起 */
  autoStart: boolean
  /** 引擎未启动时模型选择器里的兜底条目 */
  fallbackModels: Array<{ id: string; name: string; contextWindow: number; maxTokens?: number }>
  /** 是否把 reasoning_content 作为 reasoning 块回传 */
  emitReasoning: boolean
  /**
   * 工具白名单 —— 只作用于 ninfer 本地 provider 的请求，云端路由不受影响。
   * 238 个工具 schema ≈ 67K tokens，是 12G 卡首字慢（冷 prefill ≈145s）的最大单因；
   * 缩到 20 个 ≈5K，首字降到十几秒。`前缀*` 支持通配。空数组 = 不裁剪。
   */
  toolAllowlist: string[]
  /** 折叠 system 的 <available_skills> 描述段（≈19K tokens → ≈1.5K），技能仍可用 skill 工具加载 */
  slimSkills: boolean
  /** 模型选择器初始思考强度；本地量化模型默认 minimal，防长思考烧预算 */
  defaultEffort: string
  /** 每请求 payload 体积统计写入该文件（ASCII 路径；空则不写） */
  statsPath: string
}

export const Config: z<Config> = z.object({
  provider: z.string().default('ninfer'),
  displayName: z.string().default('NInfer 本地 · 5070Ti 12G'),
  baseURL: z.string().default('http://127.0.0.1:1234/v1'),
  engineDir: z.string().default('D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx'),
  autoStart: z.boolean().default(false),
  fallbackModels: z.array(z.object({
    id: z.string(),
    name: z.string(),
    contextWindow: z.number().default(262144),
    maxTokens: z.number().default(8192),
  })).default([{
    id: 'qwen3.8-27b-ablit-swift15-iq2s',
    name: 'Qwen3.8-27B 无审查 · IQ2_S · MTP',
    contextWindow: 262144,
    maxTokens: 8192,
  }]),
  emitReasoning: z.boolean().default(true),
  toolAllowlist: z.array(z.string()).default([
    // 文件 / 执行
    'write', 'read', 'edit', 'ops_bash', 'pwsh',
    'ops_glob', 'ops_grep', 'ops_inspect_local_file', 'ops_replace',
    // 会话 / 协作
    'skill', 'todo_write', 'ask_user_question', 'present',
    'subagent', 'subagent_fork',
    // 检索
    'web_search', 'web_fetch',
    // 本引擎运维面
    'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params',
  ]),
  slimSkills: z.boolean().default(true),
  defaultEffort: z.string().default('minimal'),
  statsPath: z.string().default(''),
}) as unknown as z<Config>

/** 字段映射值：DSH 的字段声明（required 为作者侧标记，不进入 provider schema）。 */
type FieldSpec = Record<string, unknown> & { required?: boolean }

/** provider 侧参数 JSON Schema：根恒为 object。 */
type ParamSchema = { type: 'object'; properties: Record<string, unknown>; required?: string[] }

/** 字段映射 → JSON Schema。字段内 required:true 收进根 required，其余键（type/enum/description）原样保留。 */
function paramSchema(spec: Record<string, FieldSpec> = {}): ParamSchema {
  const properties: Record<string, unknown> = {}
  const required: string[] = []
  for (const [key, field] of Object.entries(spec)) {
    const { required: req, ...rest } = field
    properties[key] = rest
    if (req === true) required.push(key)
  }
  return required.length > 0 ? { type: 'object', properties, required } : { type: 'object', properties }
}

/**
 * 工具注册的本地包装：等价 @deepseek-ai/dsh-tools 的 defineTool 在参数投影上的行为。
 * 不投影（字段映射原样出网）时 provider 报：
 * schema must be a JSON Schema of 'type: "object"', got 'type: null'.
 */
function tool<T extends { parameters: Record<string, FieldSpec> }>(def: T): T {
  return { ...def, parameters: paramSchema(def.parameters) as T['parameters'] }
}

export function apply(ctx: Context, config: Config): void {
  const manager = new NinferManager(config.engineDir)

  // ── 1) 模型后端 ─────────────────────────────────────────────────────────
  const profile: NinferProfile = {
    baseURL: config.baseURL,
    displayName: config.displayName,
    fallbackModels: config.fallbackModels,
    emitReasoning: config.emitReasoning,
    timeoutMs: 8000,
    // 本地专属瘦身：只影响 ninfer 这一路请求（云端 provider 各自 adapter，不经过这里）
    toolAllowlist: config.toolAllowlist,
    slimSkills: config.slimSkills,
    defaultEffort: config.defaultEffort,
    statsPath: config.statsPath || undefined,
  }
  const adapter = new NinferAdapter(profile)
  ctx.effect(
    () => ctx.llm.registerAdapter([config.provider], adapter),
    `dsh-ninfer-local: llm route "${config.provider}"`,
  )

  if (config.autoStart) {
    void manager.start().catch((error) => {
      ctx.logger?.warn?.(`dsh-ninfer-local: autoStart failed — ${String(error)}`)
    })
  }

  // ── 2) 运维工具 ─────────────────────────────────────────────────────────
  const textOut = (value: unknown) => [{ type: 'text' as const, text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) }]

  ctx.effect(() => ctx.tools.register(tool({
    name: 'ninfer_status',
    description: '本地 NInfer 引擎状态：是否运行、当前模型、上下文、参数、日志尾。',
    parameters: {},
    output: { schema: { type: 'object' }, render: (_a: unknown, v: unknown) => textOut(v) },
    async execute() {
      const st = await manager.status()
      return {
        running: st.running,
        pid: st.pid,
        baseURL: st.baseURL,
        model: st.model,
        contextWindow: st.contextWindow,
        params: st.params,
        modelFiles: manager.listModels().map((m) => `${m.file} (${(m.bytes / 2 ** 30).toFixed(2)} GiB)`),
        activeModelFile: st.modelFile,
        recentLogs: st.logs,
      }
    },
  })), 'dsh-ninfer-local: status tool')

  ctx.effect(() => ctx.tools.register(tool({
    name: 'ninfer_engine',
    description: 'NInfer 引擎启停：action=start|stop|restart。restart 可同时改参数。',
    parameters: {
      action: { type: 'string', required: true, description: 'start | stop | restart' },
      deviceKV: { type: 'number', description: 'GPU 页池 token 数' },
      hostKVMiB: { type: 'number', description: 'Host KV MiB' },
      kvDtype: { type: 'string', description: 'nvfp4 | rk4v4' },
      prefillChunk: { type: 'number', description: 'prefill 分块' },
      draftTokens: { type: 'number', description: 'MTP 草稿 token 数' },
      reasoningEffort: { type: 'string', description: 'none|minimal|low|medium|high|xhigh|max' },
      maxContext: { type: 'number', description: '逻辑上下文上限' },
      vision: { type: 'string', description: 'off | cpu | overlay' },
      port: { type: 'number', description: '引擎端口' },
    },
    output: { schema: { type: 'object' }, render: (_a: unknown, v: unknown) => textOut(v) },
    async execute(args: Record<string, unknown>) {
      const overrides: Partial<EngineParams> = {}
      for (const k of ['deviceKV', 'hostKVMiB', 'prefillChunk', 'draftTokens', 'maxContext', 'port'] as const) {
        if (typeof args[k] === 'number') overrides[k] = args[k] as never
      }
      if (typeof args.kvDtype === 'string') overrides.kvDtype = args.kvDtype as never
      if (typeof args.reasoningEffort === 'string') overrides.reasoningEffort = args.reasoningEffort as never
      if (typeof args.vision === 'string') overrides.vision = args.vision as never

      const action = String(args.action ?? 'status')
      if (action === 'stop') {
        await manager.stop()
        return { ok: true, action, running: false }
      }
      if (action === 'start') {
        const st = await manager.start(overrides)
        return { ok: true, action, running: st.running, model: st.model, contextWindow: st.contextWindow, params: st.params }
      }
      if (action === 'restart') {
        const st = await manager.restart(overrides)
        return { ok: true, action, running: st.running, model: st.model, contextWindow: st.contextWindow, params: st.params }
      }
      throw new Error(`unknown action: ${action}`)
    },
  })), 'dsh-ninfer-local: engine tool')

  ctx.effect(() => ctx.tools.register(tool({
    name: 'ninfer_model',
    description: 'NInfer 模型管理：action=list|switch|active。switch 后需 restart 生效。',
    parameters: {
      action: { type: 'string', required: true, description: 'list | switch | active' },
      file: { type: 'string', description: 'switch 时的 .ninfer 文件名' },
      restartNow: { type: 'boolean', description: 'switch 后立即重启引擎' },
    },
    output: { schema: { type: 'object' }, render: (_a: unknown, v: unknown) => textOut(v) },
    async execute(args: { action: string; file?: string; restartNow?: boolean }) {
      if (args.action === 'list') {
        return {
          models: manager.listModels().map((m) => ({ file: m.file, gib: +(m.bytes / 2 ** 30).toFixed(2) })),
          active: manager.activeModelFile(),
        }
      }
      if (args.action === 'active') return { active: manager.activeModelFile() }
      if (args.action === 'switch') {
        if (!args.file) throw new Error('file required')
        const file = manager.switchModel(args.file)
        if (args.restartNow) {
          const st = await manager.restart()
          return { ok: true, switchedTo: file, restarted: true, running: st.running, model: st.model }
        }
        return { ok: true, switchedTo: file, restarted: false, note: '下次 ninfer_engine start/restart 生效' }
      }
      throw new Error(`unknown action: ${args.action}`)
    },
  })), 'dsh-ninfer-local: model tool')

  ctx.effect(() => ctx.tools.register(tool({
    name: 'ninfer_params',
    description: 'NInfer 关键参数读写：get 或 set（deviceKV/hostKV/kvDtype/prefillChunk/draftTokens/reasoningEffort/maxContext/vision/port）。set 默认需 restart 生效。',
    parameters: {
      action: { type: 'string', required: true, description: 'get | set | defaults' },
      deviceKV: { type: 'number' },
      hostKVMiB: { type: 'number' },
      kvDtype: { type: 'string' },
      prefillChunk: { type: 'number' },
      draftTokens: { type: 'number' },
      reasoningEffort: { type: 'string', description: 'none|minimal|low|medium|high|xhigh|max' },
      maxContext: { type: 'number' },
      vision: { type: 'string' },
      port: { type: 'number' },
      restartNow: { type: 'boolean' },
    },
    output: { schema: { type: 'object' }, render: (_a: unknown, v: unknown) => textOut(v) },
    async execute(args: Record<string, unknown>) {
      if (args.action === 'defaults') return DEFAULT_PARAMS
      if (args.action === 'get') return manager.readParams()
      const patch: Partial<EngineParams> = {}
      for (const k of ['deviceKV', 'hostKVMiB', 'prefillChunk', 'draftTokens', 'maxContext', 'port'] as const) {
        if (typeof args[k] === 'number') patch[k] = args[k] as never
      }
      if (typeof args.kvDtype === 'string') patch.kvDtype = args.kvDtype as never
      if (typeof args.reasoningEffort === 'string') patch.reasoningEffort = args.reasoningEffort as never
      if (typeof args.vision === 'string') patch.vision = args.vision as never
      const next = manager.writeParams(patch)
      if (args.restartNow) {
        const st = await manager.restart()
        return { ok: true, params: next, restarted: true, running: st.running }
      }
      return { ok: true, params: next, restarted: false, note: '下次 start/restart 生效' }
    },
  })), 'dsh-ninfer-local: params tool')
}
