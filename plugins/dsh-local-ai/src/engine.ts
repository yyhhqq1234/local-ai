/**
 * NInfer 引擎/模型管理器 —— 纯 Node 实现，无第三方依赖。
 *
 * 设计要点：
 * - 引擎进程用 windowsHide 隐藏窗口拉起，PID 落盘到 run/engine.pid
 *   （不可用 detached：Windows 的 DETACHED_PROCESS 会让 pwsh 秒退 code=0）
 * - 所有读写都限制在 engineDir 内（模型目录、配置文件、日志）
 * - 参数以 JSON 落盘（config/engine.json），启动时渲染成 PowerShell 调用
 *
 * 2026-11-08 多档位（ENGINE_PROFILES）：
 *   csunx-27b —— 27B，走 ninfer-csunx/run-engine.ps1（原逻辑逐字保留）
 *   build-9b  —— 9B，直启 _tools/ninfer-build/apps/ninfer-serve.exe（实测可用配置）
 *   两档互斥运行，共用 params.port，故 baseURL 不变。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, openSync, closeSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'
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
  /** 引擎档位：csunx-27b（默认）| build-9b */
  profile: string
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
  /** 显式指定的模型文件名（可选） */
  modelFile?: string
}

/** 引擎档位定义 */
interface EngineProfile {
  label: string
  kind: 'launcher' | 'exe'
  /** 该档位真实引擎可执行（27B 与 9B 进程同名 ninfer-serve.exe，只能靠路径区分） */
  engineExe?: string
  engineDir: string
  /** launcher 模式：run-engine.ps1 所在目录；exe 模式：exe 所在目录（cwd） */
  exe?: string
  modelDirs: string[]
  defaultModel?: string
  /** exe 模式：强制覆盖 maxContext（引擎实际容量） */
  maxContext?: number
  /** exe 模式：固定附加参数 */
  extraArgs?: string[]
  /** exe 模式：视觉开关参数名 */
  visionFlag?: string
}

export const ENGINE_PROFILES: Record<string, EngineProfile> = {
  'csunx-27b': {
    label: '27B · csunx launcher（原路径，行为不变）',
    kind: 'launcher',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx',
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx/runtime/engine/ninfer-serve.exe',
    modelDirs: [
      'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx/model',
      'D:/BaiduNetdiskDownload/Local-AI/ninfer-27b-kv-stream-3arch-20261019/model',
    ],
    defaultModel: '',
  },
  'build-9b': {
    label: '9B · ninfer-build 直启（chunk128 + no-thinking）',
    kind: 'exe',
    exe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps',
    modelDirs: ['D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out'],
    defaultModel: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer',
    maxContext: 4096,
    // 实测：prefill 块宽 >128 时 L03 proj_k/proj_v（1024 行段）NaN → 500 → 503；
    //      缺 --no-thinking 时内容全落 reasoning_content、message.content 为空。
    extraArgs: ['--greedy', '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
    visionFlag: '--vision',
  },
}

const DEFAULT_PROFILE = 'csunx-27b'

export const DEFAULT_PARAMS: EngineParams = {
  profile: DEFAULT_PROFILE,
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
  profile: string
  profiles: Record<string, string>
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

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
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

  // ---------- 档位 ----------
  profileOf(name: string): EngineProfile {
    return ENGINE_PROFILES[name] ?? ENGINE_PROFILES[DEFAULT_PROFILE]
  }

  // ---------- 模型 ----------
  listModels(): Array<{ file: string; bytes: number; path: string; dir: string; profile: string }> {
    const out: Array<{ file: string; bytes: number; path: string; dir: string; profile: string }> = []
    for (const [name, prof] of Object.entries(ENGINE_PROFILES)) {
      for (const d of prof.modelDirs) {
        if (!existsSync(d)) continue
        for (const f of readdirSync(d)) {
          if (!f.endsWith('.ninfer')) continue
          const p = join(d, f)
          out.push({ file: f, bytes: statSync(p).size, path: p, dir: d, profile: name })
        }
      }
    }
    return out.sort((a, b) => a.file.localeCompare(b.file) || a.profile.localeCompare(b.profile))
  }

  /** 当前档位下的模型对象（带绝对 path，直启模式要用） */
  activeModel(): { file: string; bytes: number; path: string; dir: string; profile: string } | undefined {
    const params = this.readParams()
    const prof = this.profileOf(params.profile)
    const models = this.listModels()
    if (!models.length) return undefined
    const mine = models.filter((m) => m.profile === params.profile)
    if (params.modelFile) {
      const hit = mine.find((m) => m.file === params.modelFile)
      if (hit) return hit
    }
    if (prof.defaultModel) {
      const d = mine.find((m) => m.file === prof.defaultModel)
      if (d) return d
    }
    return mine[0] ?? models[0]
  }

  activeModelFile(): string | undefined {
    const m = this.activeModel()
    return m ? m.file : undefined
  }

  switchModel(file: string): string {
    const models = this.listModels()
    if (!models.some((m) => m.file === file)) throw new Error(`model not found: ${file}`)
    this.writeParams({ modelFile: file })
    return file
  }

  // ---------- 引擎身份 ----------
  engineInfo(): { profile: string; label: string; kind: string; exe: string; exists: boolean; bytes?: number; modelDirs: string[] } {
    const params = this.readParams()
    const prof = this.profileOf(params.profile)
    const exe = prof.engineExe ?? prof.exe ?? ''
    let bytes: number | undefined
    try { bytes = statSync(exe).size } catch { bytes = undefined }
    return {
      profile: params.profile,
      label: prof.label,
      kind: prof.kind,
      exe,
      exists: bytes !== undefined,
      bytes,
      modelDirs: prof.modelDirs,
    }
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
        contextWindow = Number(first.context_window ?? first.max_model_len ?? meta.n_ctx ?? 0) || undefined
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
      profile: params.profile,
      profiles: Object.fromEntries(Object.entries(ENGINE_PROFILES).map(([k, v]) => [k, v.label])),
      engine: this.engineInfo(),
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
    const model = this.activeModel()
    if (!model) throw new Error(`no .ninfer model in profile=${params.profile}`)
    const prof = this.profileOf(params.profile)
    // 硬约束：27B 与 9B 引擎一一对应，模型必须落在本档位的模型目录里
    const allowed = prof.modelDirs ?? []
    if (allowed.length && !allowed.includes(model.dir)) {
      throw new Error('模型 ' + model.file + ' 不属于档位 ' + params.profile +
        ' 的引擎（应在 ' + allowed.join(' | ') + '）')
    }
    const logDir = join(this.dir, 'logs')

    let child: ReturnType<typeof spawn> | undefined
    let exe = ''
    let engineDir: string

    if (prof.kind === 'exe') {
      // 直启：exe 自身即服务端（不经 pwsh、不经 run-engine.ps1）
      if (!prof.exe) throw new Error('profile ' + params.profile + ' has no exe')
      if (!existsSync(prof.exe)) throw new Error('engine exe missing: ' + prof.exe)
      const args: string[] = [model.path,
        '--max-context', String(prof.maxContext ?? params.maxContext),
        '--port', String(params.port)]
      for (const a of prof.extraArgs ?? []) args.push(a)
      if (prof.visionFlag && params.vision !== 'off') args.push(prof.visionFlag)
      exe = prof.exe
      engineDir = prof.engineDir
      child = spawn(exe, args, { cwd: engineDir, windowsHide: true, stdio: 'ignore' })
    } else {
      engineDir = prof.engineDir
      const script = join(engineDir, 'run-engine.ps1')
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
        '-ModelFile', model.file,
      ]
      if (params.vision === 'off') args.push('-NoVision')
      else if (params.vision === 'cpu') args.push('-VisionCpu')
      exe = resolvePwsh()
      child = spawn(exe, args, { cwd: engineDir, windowsHide: true, stdio: 'ignore' })
    }

    this.child = child
    child.on('error', (e: Error) => {
      console.error(`[dsh-ninfer-local] engine spawn failed (exe=${exe}):`, e.message)
    })
    child.unref?.()
    if (child.pid) writeFileSync(this.pidPath, String(child.pid), 'utf8')

    const deadline = Date.now() + 150_000
    while (Date.now() < deadline) {
      await sleep(1500)
      const s = await this.status()
      if (s.running) return s
    }
    throw new Error(`engine did not become ready within 150s (profile=${params.profile}, model=${model.file}) — 检查 ${logDir}`)
  }

  async stop(): Promise<void> {
    try {
      const pidRaw = readFileSync(this.pidPath, 'utf8').trim()
      if (pidRaw) spawn('taskkill', ['/F', '/T', '/PID', pidRaw], { windowsHide: true, stdio: 'ignore' })
    } catch { /* no pid file */ }
    // 兜底：只杀「可执行路径 == 本档位引擎」的进程。
    // 绝不能用 taskkill /IM ninfer-serve.exe —— 27B 与 9B 进程名完全相同，会误杀另一个引擎。
    const info = this.engineInfo()
    if (info.exe) {
      const esc = info.exe.replace(/'/g, "''")
      const ps = "Get-Process -Name ninfer-serve -ErrorAction SilentlyContinue | " +
        "Where-Object { $_.Path -and $_.Path.ToLower() -eq '" + esc.toLowerCase() + "' } | " +
        "ForEach-Object { Stop-Process -Id $_.Id -Force }"
      spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps], { windowsHide: true, stdio: 'ignore' })
    }
    try { rmSync(this.pidPath) } catch { /* ignore */ }
    const deadline = Date.now() + 25_000
    while (Date.now() < deadline) {
      await sleep(800)
      const s = await this.status()
      if (!s.running) return
    }
    throw new Error('engine still answering after kill')
  }

  async restart(overrides: Partial<EngineParams> = {}): Promise<EngineState> {
    await this.stop()
    return this.start(overrides)
  }
}
