// 1) 模型下拉 = 目录(27B+9B 全量) + 运行中；2) 选谁就切谁（ensureModel）；3) 9B 思考档按 effort 决定 --no-thinking
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

// ── 1) listModels：目录全量 + 运行中 ─────────────────────────────
rep('listModels catalog',
`  async listModels(provider) {
    try {
      const d = await httpJson(\`\${this.profile.baseURL}/models\`, this.profile.timeoutMs ?? 5000)
      const live = (d?.data ?? [])
      if (live.length) return live.map((m) => ({ provider, id: m.id, name: m.id }))
    } catch { /* 引擎没起，走下面 */ }
    // 引擎没起：给"当前档位的现行模型"（27B 档位给 27B、9B 档位给 9B），
    // 而不是硬编码 fallbackModels —— 否则选中 27B id 去请求 9B 引擎会 model_not_found 404。
    const activeId = typeof this.profile.activeModelId === 'function' ? this.profile.activeModelId() : undefined
    if (activeId) return [{ provider, id: activeId, name: activeId + '（未启动）' }]
    return (this.profile.fallbackModels ?? []).map((m) => ({ provider, id: m.id, name: m.name }))
  }`,
`  async listModels(provider) {
    const out = []
    const seen = new Set()
    // (a) 本地模型目录：27B 与 9B 全部列出（不管当前跑的是哪个）
    const catalog = typeof this.profile.modelCatalog === 'function' ? this.profile.modelCatalog() : []
    for (const m of catalog) {
      if (!m || !m.id || seen.has(m.id)) continue
      seen.add(m.id)
      out.push({ provider, id: m.id, name: m.name })
    }
    // (b) 引擎正在跑的 id（可能与目录文件名不同，如 27B 自报 kittyrev-G7-600）置顶
    try {
      const d = await httpJson(\`\${this.profile.baseURL}/models\`, this.profile.timeoutMs ?? 5000)
      const live = (d?.data ?? []).filter((m) => m && m.id && !seen.has(m.id))
      for (const m of live) {
        seen.add(m.id)
        out.unshift({ provider, id: m.id, name: m.id + '（运行中）' })
      }
    } catch { /* 引擎没起 */ }
    if (out.length) return out
    // (c) 兜底：当前档位的现行模型
    const activeId = typeof this.profile.activeModelId === 'function' ? this.profile.activeModelId() : undefined
    if (activeId) return [{ provider, id: activeId, name: activeId + '（未启动）' }]
    return (this.profile.fallbackModels ?? []).map((m) => ({ provider, id: m.id, name: m.name }))
  }`)

// ── 2) 请求前确保引擎+模型就位 ───────────────────────────────────
rep('ensureModel call',
`    let res
    try {
      res = await fetch(\`\${this.profile.baseURL}/chat/completions\`, {`,
`    if (typeof this.profile.ensureModel === 'function') {
      try { await this.profile.ensureModel(options.model) } catch (e) { console.error('[dsh-ninfer-local] ensureModel:', e && e.message) }
    }

    let res
    try {
      res = await fetch(\`\${this.profile.baseURL}/chat/completions\`, {`)

// ── 3) 思考开关同步到引擎模板（9B 认 chat_template_kwargs.enable_thinking）──
rep('enable_thinking',
`      body.reasoning_effort = eff
    }`,
`      body.reasoning_effort = eff
      // 9B（ninfer-build）尊重 chat_template_kwargs.enable_thinking；27B 引擎忽略该字段
      body.chat_template_kwargs = { ...(body.chat_template_kwargs || {}), enable_thinking: eff !== 'none' }
    }`)

// ── 4) build-9b：--no-thinking 只在 effort=none 时加 ─────────────
rep('9b no-thinking conditional',
`      const eargs = [model.path,
        '--max-context', String(prof.maxContext ?? params.maxContext),
        '--port', String(params.port)]
      const effort = String(params.reasoningEffort ?? '')
      for (const a of prof.extraArgs ?? []) {
        // --no-thinking 只在 effort=none 时加；否则保留思考通道（映射 enable_thinking）
        if (a === '--no-thinking' && effort && effort !== 'none') continue
        eargs.push(a)
      }`,
`      const args = [model.path,
        '--max-context', String(prof.maxContext ?? params.maxContext),
        '--port', String(params.port)]
      const effort = String(params.reasoningEffort ?? '')
      for (const a of prof.extraArgs ?? []) {
        // --no-thinking 只在 effort=none 时加；否则让引擎保留思考通道（映射 enable_thinking）
        if (a === '--no-thinking' && effort && effort !== 'none') continue
        args.push(a)
      }`)

// ── 5) apply()：把目录与 ensureModel 交给 adapter ────────────────
rep('adapter callbacks',
`      activeModelId: () => {
        try {
          const f = manager.activeModelFile()
          return f ? f.replace(/\\.ninfer$/i, '') : undefined
        } catch { return undefined }
      },`,
`      activeModelId: () => {
        try {
          const f = manager.activeModelFile()
          return f ? f.replace(/\\.ninfer$/i, '') : undefined
        } catch { return undefined }
      },
      // 模型目录：27B 与 9B 全量列出，名字后缀标档位，选择器里一眼能分
      modelCatalog: () => {
        try {
          return manager.listModels().map((m) => ({
            id: m.file.replace(/\\.ninfer$/i, ''),
            name: m.file.replace(/\\.ninfer$/i, '') + ' · ' + (ENGINE_PROFILES[m.profile]?.label ?? m.profile) +
              ' (' + (m.bytes / 2 ** 30).toFixed(2) + ' GiB)',
            profile: m.profile,
            file: m.file,
          }))
        } catch { return [] }
      },
      // 选中的模型不在跑 → 切模型/档位并重启；已经在跑则不动
      ensureModel: async (modelId) => {
        const want = String(modelId || '')
        if (!want) return
        const all = manager.listModels()
        const hit = all.find((m) => m.file.replace(/\\.ninfer$/i, '') === want)
        if (!hit) return                       // 不在目录里（如引擎自报的别名）→ 不折腾
        const params = manager.readParams()
        const sameModel = String(params.modelFile || '') === hit.file
        const sameProfile = params.profile === hit.profile
        const st = await manager.status()
        if (sameModel && sameProfile) {
          if (!st.running) await manager.start({})
          return
        }
        manager.writeParams({ profile: hit.profile, modelFile: hit.file })
        await manager.restart({})
      },`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
console.log('bytes=' + s.length)
