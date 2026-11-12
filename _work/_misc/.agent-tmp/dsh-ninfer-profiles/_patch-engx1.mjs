// 给 dsh-ninfer-local 增加「引擎档位（profile）」：csunx-27b（原路径不变） + build-9b（直启 ninfer-build）
// 只改 lib/index.js（运行时产物）；src/*.ts 同步由后续手工对齐。改完必须 node --check。
import fs from 'node:fs'

const P = 'lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected exactly 1 occurrence, got ${n}`)
  s = s.replace(from, to)
  hits.push(name)
}

// ── 1) 档位表 + DEFAULT_PARAMS.profile ─────────────────────────────
rep('profiles+DEFAULT_PARAMS',
`const DEFAULT_PARAMS = {
  deviceKV: 36864,`,
`// ── 引擎档位 ────────────────────────────────────────────────────────
// 一个插件同时管两套部署：27B 走 csunx 的 run-engine.ps1（原样不动），
// 9B 走自建 ninfer-build 的 exe 直启（2026-11-08 实测可用配置）。
// 两者互斥运行（同名镜像 ninfer-serve.exe），共用 params.port，故 baseURL 无需变。
const ENGINE_PROFILES = {
  'csunx-27b': {
    label: '27B · csunx launcher（原路径）',
    kind: 'launcher',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx',
    modelDirs: [
      'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx/model',
      'D:/BaiduNetdiskDownload/Local-AI/ninfer-27b-kv-stream-3arch-20261019/model',
    ],
    defaultModel: '',
  },
  'build-9b': {
    label: '9B · ninfer-build 直启（chunk128 + no-thinking）',
    kind: 'exe',
    exe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/infer-build/apps/ninfer-serve.exe',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/_tools/infer-build/apps',
    modelDirs: [
      'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out',
    ],
    defaultModel: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer',
    maxContext: 4096,
    // 实测依据：prefill 块宽 >128 时 L03 的 proj_k/proj_v（1024 行段）NaN → 500 → 503；
    //           不加 --no-thinking 时内容全落 reasoning_content、content 为空。
    extraArgs: ['--greedy', '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
    visionFlag: '--vision',
  },
}

const DEFAULT_PROFILE = 'csunx-27b'

const DEFAULT_PARAMS = {
  profile: DEFAULT_PROFILE,
  deviceKV: 36864,`)

// ── 2) 直启 spawnExe（与 spawnEngine 同款保护：windowsHide + 日志 fd + error 监听）──
rep('spawnExe',
`/** launcher 输出尾部（启动失败时用来解释原因） */`,
`function spawnExe(args, cwd, logDir, exePath) {
  let fd = -1
  try {
    mkdirSync(logDir, { recursive: true })
    fd = openSync(join(logDir, 'launcher.log'), 'a')
  } catch { /* 落盘失败退回 ignore */ }
  const stdio = fd >= 0 ? ['ignore', fd, fd] : 'ignore'
  const child = spawn(exePath, args, { cwd, windowsHide: true, stdio })
  if (fd >= 0) { try { closeSync(fd) } catch { /* 子进程已 dup */ } }
  const ready = new Promise((res, rej) => {
    child.once('spawn', () => res(exePath))
    child.on('error', (e) => {
      try {
        writeFileSync(join(logDir, 'spawn-error.log'),
          \`\${new Date().toISOString()} exe=\${exePath}\\n\${e && e.stack}\\n\`, 'utf8')
      } catch { /* ignore */ }
      rej(new Error(\`engine exe spawn failed (\${exePath}): \${e && e.message}\`))
    })
  })
  ready.catch(() => { /* 由调用方处理 */ })
  child.unref()
  return { child, exe: exePath, ready }
}

/** launcher 输出尾部（启动失败时用来解释原因） */`)

// ── 3) 模型枚举：按档位汇总，带 profile 标签 ──────────────────────
rep('listModels',
`  listModels() {
    const dirs = [join(this.dir, 'model'), join(this.dir, '..', 'ninfer-27b-kv-stream-3arch-20261019', 'model')]
    const out = []
    for (const d of dirs) {
      if (!existsSync(d)) continue
      for (const f of readdirSync(d)) {
        if (!f.endsWith('.ninfer')) continue
        const p = join(d, f)
        out.push({ file: f, bytes: statSync(p).size, path: p, dir: d })
      }
    }
    return out.sort((a, b) => a.file.localeCompare(b.file))
  }

  activeModelFile() {
    const models = this.listModels()
    if (!models.length) return undefined
    const want = this.readParams().modelFile
    if (want && models.some((m) => m.file === want)) return want
    return models[0].file
  }`,
`  profileOf(name) {
    return ENGINE_PROFILES[name] ?? ENGINE_PROFILES[DEFAULT_PROFILE]
  }

  listModels() {
    const out = []
    for (const [name, prof] of Object.entries(ENGINE_PROFILES)) {
      for (const d of prof.modelDirs ?? []) {
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

  /** 当前档位下的模型（切换档位不影响另一档的 modelFile 记忆） */
  activeModel() {
    const params = this.readParams()
    const prof = this.profileOf(params.profile)
    const models = this.listModels()
    if (!models.length) return undefined
    const mine = models.filter((m) => m.profile === params.profile)
    const want = params.modelFile
    if (want) {
      const hit = mine.find((m) => m.file === want)
      if (hit) return hit
    }
    if (prof.defaultModel) {
      const d = mine.find((m) => m.file === prof.defaultModel)
      if (d) return d
    }
    return mine[0] ?? models[0]
  }

  activeModelFile() {
    const m = this.activeModel()
    return m ? m.file : undefined
  }`)

// ── 4) start()：按档位分流（launcher 原逻辑逐字保留）────────────
rep('start',
`    const params = { ...this.readParams(), ...overrides }
    if (Object.keys(overrides).length) this.writeParams(overrides)
    const modelFile = this.activeModelFile()
    if (!modelFile) throw new Error('no .ninfer model found')

    const script = join(this.dir, 'run-engine.ps1')
    if (!existsSync(script)) throw new Error('run-engine.ps1 missing: ' + script)

    const args = [
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script,
      '-DeviceKV', String(params.deviceKV),
      '-HostKVMiB', String(params.hostKVMiB),
      '-KVDType', String(params.kvDtype),
      '-PrefillChunk', String(params.prefillChunk),
      '-DraftTokens', String(params.draftTokens),
      '-ReasoningEffort', params.reasoningEffort,
      '-MaxContext', String(params.maxContext),
      '-EnginePort', String(params.port),
      '-ModelFile', modelFile,
    ]
    if (params.vision === 'off') args.push('-NoVision')
    else if (params.vision === 'cpu') args.push('-VisionCpu')

    const { child, exe, ready } = spawnEngine(args, this.dir, join(this.dir, 'logs'))
    await ready // 拉起失败（ENOENT 等）在这里显式抛出，不再等满 150s，也不打穿宿主`,
`    const params = { ...this.readParams(), ...overrides }
    if (Object.keys(overrides).length) this.writeParams(overrides)
    const model = this.activeModel()
    if (!model) throw new Error('no .ninfer model found (profile=' + params.profile + ')')
    const prof = this.profileOf(params.profile)
    const logDir = join(this.dir, 'logs')

    let child, exe, ready
    if (prof.kind === 'exe') {
      // 直启模式：exe 自己就是服务端（不经 pwsh、不经 run-engine.ps1）
      if (!existsSync(prof.exe)) throw new Error('engine exe missing: ' + prof.exe)
      const args = [model.path,
        '--max-context', String(prof.maxContext ?? params.maxContext),
        '--port', String(params.port)]
      for (const a of prof.extraArgs ?? []) args.push(a)
      if (prof.visionFlag && params.vision !== 'off') args.push(prof.visionFlag)
      ;({ child, exe, ready } = spawnExe(args, prof.engineDir ?? this.dir, logDir, prof.exe))
    } else {
      const engineDir = prof.engineDir ?? this.dir
      const script = join(engineDir, 'run-engine.ps1')
      if (!existsSync(script)) throw new Error('run-engine.ps1 missing: ' + script)
      const args = [
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script,
        '-DeviceKV', String(params.deviceKV),
        '-HostKVMiB', String(params.hostKVMiB),
        '-KVDType', String(params.kvDtype),
        '-PrefillChunk', String(params.prefillChunk),
        '-DraftTokens', String(params.draftTokens),
        '-ReasoningEffort', params.reasoningEffort,
        '-MaxContext', String(params.maxContext),
        '-EnginePort', String(params.port),
        '-ModelFile', model.file,
      ]
      if (params.vision === 'off') args.push('-NoVision')
      else if (params.vision === 'cpu') args.push('-VisionCpu')
      ;({ child, exe, ready } = spawnEngine(args, engineDir, logDir))
    }
    await ready // 拉起失败（ENOENT 等）在这里显式抛出，不再等满 150s，也不打穿宿主`)

// ── 5) 参数白名单接受 profile ────────────────────────────────────
rep('pickParams',
`  const str = ['kvDtype', 'reasoningEffort', 'vision']`,
`  const str = ['kvDtype', 'reasoningEffort', 'vision', 'profile']`)

// ── 6) 工具描述里补 profile ──────────────────────────────────────
rep('engine tool param',
`      port: { type: 'number', description: '引擎监听端口（1234）' },
    },
    output: OUT,
    async execute(args) {
      const a = args && typeof args === 'object' ? args : {}
      const action = String(a.action ?? 'start')
      const ov = pickParams(a)
      if (action === 'stop') {`,
`      port: { type: 'number', description: '引擎监听端口（1234）' },
      profile: { type: 'string', description: '引擎档位：csunx-27b（默认，27B launcher）| build-9b（9B 直启）' },
    },
    output: OUT,
    async execute(args) {
      const a = args && typeof args === 'object' ? args : {}
      const action = String(a.action ?? 'start')
      const ov = pickParams(a)
      if (action === 'stop') {`)

rep('params tool profile',
`      port: { type: 'number', description: '引擎端口' },
      restartNow: { type: 'boolean', description: 'set 后立即重启生效（默认 false）' },`,
`      port: { type: 'number', description: '引擎端口' },
      profile: { type: 'string', description: '引擎档位：csunx-27b | build-9b' },
      restartNow: { type: 'boolean', description: 'set 后立即重启生效（默认 false）' },`)

// ── 7) status 暴露档位与可用档位表 ────────────────────────────────
rep('status profile',
`    return { running, pid, port: params.port, baseURL, model, contextWindow, params, modelFile: this.activeModelFile(), logs: this.tailLogs(8) }`,
`    return {
      running, pid, port: params.port, baseURL, model, contextWindow, params,
      profile: params.profile,
      profiles: Object.fromEntries(Object.entries(ENGINE_PROFILES).map(([k, v]) => [k, v.label])),
      modelFile: this.activeModelFile(),
      logs: this.tailLogs(8),
    }`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
console.log('bytes=' + s.length)
