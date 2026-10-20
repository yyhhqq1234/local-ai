/**
 * NInfer 引擎/模型管理器 —— 纯 Node 实现，无第三方依赖。
 *
 * 设计要点：
 * - 引擎进程用 windowsHide 隐藏窗口拉起，PID 落盘到 run/engine.pid
 *   （不可用 detached：Windows 的 DETACHED_PROCESS 会让 pwsh 秒退 code=0）
 * - 所有读写都限制在 engineDir 内（模型目录、配置文件、日志）
 * - 参数以 JSON 落盘（config/engine.json），启动时渲染成 PowerShell 调用
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { request } from 'node:http'

/**
 * pwsh 解析：桌面宿主进程的 PATH 里可能没有 PowerShell 7 目录（注册表 PATH 未写入），
 * 裸 spawn('pwsh') 会 ENOENT，且 error 无人监听时会以 uncaught 打穿宿主进程。
 * 故用绝对路径探测兜底。
 */
function resolvePwsh(): string {
  const cands: string[] = []
  const push = (p?: string) => { if (p) cands.push(join(p, 'pwsh.exe')) }
  push(process.env.ProgramFiles)
  push(process.env['ProgramFiles(x86)'])
  if (process.env.LOCALAPPDATA) push(join(process.env.LOCALAPPDATA, 'Microsoft', 'WindowsApps'))
  cands.push(
    'C:\\Program Files\\PowerShell\\7\\pwsh.exe',
    'C:\\Program Files (x86)\\PowerShell\\7\\pwsh.exe',
    'C:\\Program Files\\PowerShell\\7-preview\\pwsh.exe',
    'C:\\Program Files (x86)\\PowerShell\\7-preview\\pwsh.exe',
  )
  for (const d of String(process.env.PATH ?? '').split(';')) {
    const t = d.trim()
    if (t && /powershell/i.test(t)) cands.push(join(t, 'pwsh.exe'))
  }
  for (const c of cands) {
    try { if (existsSync(c)) return c } catch { /* ignore */ }
  }
  return 'pwsh'
}

export interface EngineParams {
  /** GPU 页池 token 数（DeviceKV） */
  deviceKV: number
  /** Host KV（MiB） */
  hostKVMiB: number
  /** KV 编码：nvfp4 / rk4v4 */
  kvDtype: 'nvfp4' | 'rk4v4'
  /** prefill 分块 */
  prefillChunk: number
  /** MTP 草稿数 */
  draftTokens: number
  /** 默认思考强度 */
  reasoningEffort: 'none' | 'minimal' | 'low' | 'medium' | 'high' | 'xhigh' | 'max'
  /** 逻辑上下文上限 */
  maxContext: number
  /** 视觉模式 */
  vision: 'off' | 'cpu' | 'overlay'
  /** 引擎端口 */
  port: number
}

export const DEFAULT_PARAMS: EngineParams = {
  deviceKV: 36864,
  hostKVMiB: 7168,
  kvDtype: 'nvfp4',
  prefillChunk: 128,
  draftTokens: 3,
  reasoningEffort: 'high',
  maxContext: 262144,
  vision: 'cpu',
  port: 1234,
}

export interface EngineState {
  running: boolean
  pid?: number
  port: number
  baseURL: string
  model?: string
  contextWindow?: number
  params: EngineParams
  modelFile?: string
  logs: string[]
}

function httpJson(url: string, timeoutMs = 3000): Promise<unknown> {
  return new Promise((res, rej) => {
    const req = request(url, { method: 'GET', timeout: timeoutMs }, (r) => {
      let body = ''
      r.setEncoding('utf8')
      r.on('data', (c) => { body += c })
      r.on('end', () => {
        try { res(JSON.parse(body)) } catch { rej(new Error(`bad json from ${url}`)) }
      })
    })
    req.on('timeout', () => { req.destroy(new Error('timeout')) })
    req.on('error', rej)
    req.end()
  })
}

export class NinferManager {
  readonly dir: string
  readonly configPath: string
  readonly pidPath: string
  private child?: ReturnType<typeof spawn>

  constructor(dir: string) {
    this.dir = resolve(dir)
    this.configPath = join(this.dir, 'config', 'engine.json')
    this.pidPath = join(this.dir, 'run', 'engine.pid')
    mkdirSync(join(this.dir, 'config'), { recursive: true })
    mkdirSync(join(this.dir, 'run'), { recursive: true })
    mkdirSync(join(this.dir, 'logs'), { recursive: true })
  }

  // ---------- 参数 ----------
  readParams(): EngineParams {
    try {
      const raw = JSON.parse(readFileSync(this.configPath, 'utf8'))
      return { ...DEFAULT_PARAMS, ...raw }
    } catch {
      return { ...DEFAULT_PARAMS }
    }
  }

  writeParams(patch: Partial<EngineParams>): EngineParams {
    const next = { ...this.readParams(), ...patch }
    writeFileSync(this.configPath, JSON.stringify(next, null, 2), 'utf8')
    return next
  }

  // ---------- 模型 ----------
  listModels(): Array<{ file: string; bytes: number; path: string }> {
    const modelDir = join(this.dir, 'model')
    if (!existsSync(modelDir)) return []
    return readdirSync(modelDir)
      .filter((f) => f.endsWith('.ninfer'))
      .map((f) => {
        const p = join(modelDir, f)
        return { file: f, bytes: statSync(p).size, path: p }
      })
      .sort((a, b) => a.file.localeCompare(b.file))
  }

  /** launcher 语义：取排序第一个；这里显式指定优先文件 */
  activeModelFile(): string | undefined {
    const params = this.readParams() as EngineParams & { modelFile?: string }
    const models = this.listModels()
    if (models.length === 0) return undefined
    if (params.modelFile && models.some((m) => m.file === params.modelFile)) return params.modelFile
    return models[0].file
  }

  switchModel(file: string): string {
    const models = this.listModels()
    if (!models.some((m) => m.file === file)) throw new Error(`model not found: ${file}`)
    this.writeParams({ modelFile: file } as Partial<EngineParams>)
    return file
  }

  // ---------- 进程 ----------
  async status(): Promise<EngineState> {
    const params = this.readParams()
    const baseURL = `http://127.0.0.1:${params.port}/v1`
    let model: string | undefined
    let contextWindow: number | undefined
    let running = false
    try {
      const d = (await httpJson(`${baseURL}/models`)) as { data?: Array<Record<string, unknown>> }
      const first = d.data?.[0]
      if (first) {
        running = true
        model = String(first.id ?? '')
        const meta = (first.meta ?? {}) as Record<string, unknown>
        contextWindow = Number(first.context_window ?? meta.n_ctx ?? 0) || undefined
      }
    } catch { /* not running */ }
    const logs = this.tailLogs(8)
    return {
      running,
      pid: this.child?.pid,
      port: params.port,
      baseURL,
      model,
      contextWindow,
      params,
      modelFile: this.activeModelFile(),
      logs,
    }
  }

  tailLogs(n = 8): string[] {
    const logDir = join(this.dir, 'logs')
    if (!existsSync(logDir)) return []
    const files = readdirSync(logDir).filter((f) => f.endsWith('.log')).sort()
    const last = files[files.length - 1]
    if (!last) return []
    try {
      const lines = readFileSync(join(logDir, last), 'utf8').split(/\r?\n/).filter(Boolean)
      return lines.slice(-n)
    } catch { return [] }
  }

  async start(overrides: Partial<EngineParams> = {}): Promise<EngineState> {
    const st = await this.status()
    if (st.running) return st
    const params = { ...this.readParams(), ...overrides }
    if (Object.keys(overrides).length) this.writeParams(overrides)
    const modelFile = this.activeModelFile()
    if (!modelFile) throw new Error('no .ninfer model in model/ — 先把模型放进 ' + join(this.dir, 'model'))

    const script = join(this.dir, 'run-engine.ps1')
    if (!existsSync(script)) throw new Error('run-engine.ps1 missing: ' + script)

    const args = [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script,
      '-DeviceKV', String(params.deviceKV),
      '-HostKVMiB', String(params.hostKVMiB),
      '-KVDType', params.kvDtype,
      '-PrefillChunk', String(params.prefillChunk),
      '-DraftTokens', String(params.draftTokens),
      '-ReasoningEffort', params.reasoningEffort,
      '-MaxContext', String(params.maxContext),
      '-EnginePort', String(params.port),
      '-ModelFile', modelFile,
    ]
    if (params.vision === 'off') args.push('-NoVision')
    else if (params.vision === 'cpu') args.push('-VisionCpu')

    const exe = resolvePwsh()
    this.child = spawn(exe, args, {
      cwd: this.dir,
      detached: false,
      windowsHide: true,
      stdio: 'ignore',
    })
    // 必须有 error 监听者：ENOENT/EACCES 否则变 uncaught，把宿主进程打穿
    this.child.on('error', (e: Error) => {
      console.error(`[dsh-ninfer-local] engine spawn failed (exe=${exe}):`, e.message)
    })
    this.child.unref?.()
    if (this.child.pid) writeFileSync(this.pidPath, String(this.child.pid), 'utf8')

    // 等就绪（最多 120s）
    const deadline = Date.now() + 120_000
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 1500))
      const s = await this.status()
      if (s.running) return s
    }
    throw new Error('engine did not become ready within 120s — 检查 logs/ 与显存占用')
  }

  async stop(): Promise<void> {
    const params = this.readParams()
    try {
      const pidRaw = readFileSync(this.pidPath, 'utf8').trim()
      if (pidRaw) spawn('taskkill', ['/F', '/T', '/PID', pidRaw], { windowsHide: true, stdio: 'ignore' })
    } catch { /* no pid file */ }
    // 兜底：按镜像名杀（本插件独占的引擎实例）
    spawn('taskkill', ['/F', '/IM', 'ninfer-serve.exe'], { windowsHide: true, stdio: 'ignore' })
    try { rmSync(this.pidPath) } catch { /* ignore */ }
    // 等端口释放
    const deadline = Date.now() + 20_000
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 800))
      const s = await this.status()
      if (!s.running) return
    }
    void params
  }

  async restart(overrides: Partial<EngineParams> = {}): Promise<EngineState> {
    await this.stop()
    return this.start(overrides)
  }
}
