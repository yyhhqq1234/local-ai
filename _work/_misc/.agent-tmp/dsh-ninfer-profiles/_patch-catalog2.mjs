// v2：模型目录全量 + ensureModel + effort→enable_thinking + 9B --no-thinking 条件化
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

// 1) listModels：目录全量（27B+9B）+ 运行中
rep('listModels',
`  async listModels(provider) {
    try {
      const d = await httpJson(\`\${this.profile.baseURL}/models\`, this.profile.timeoutMs ?? 5000)
      const live = (d?.data ?? [])
      if (live.length) return live.map((m) => ({ provider, id: m.id, name: m.id }))
    } catch { /* 引擎没起，走下面 */ }`,
`  async listModels(provider) {
    const out = []
    const seen = new Set()
    // (a) 本地模型目录：27B 与 9B 全部列出（不依赖当前跑的是哪个）
    const catalog = typeof this.profile.modelCatalog === 'function' ? this.profile.modelCatalog() : []
    for (const m of catalog) {
      if (!m || !m.id || seen.has(m.id)) continue
      seen.add(m.id)
      out.push({ provider, id: m.id, name: m.name })
    }
    // (b) 引擎正在跑的 id 置顶（27B 自报名可能与文件名不同）
    try {
      const d = await httpJson(\`\${this.profile.baseURL}/models\`, this.profile.timeoutMs ?? 5000)
      for (const m of (d?.data ?? [])) {
        if (!m || !m.id || seen.has(m.id)) continue
        seen.add(m.id)
        out.unshift({ provider, id: m.id, name: m.id + '（运行中）' })
      }
    } catch { /* 引擎没起 */ }
    if (out.length) return out`)

// 2) 请求前确保引擎与模型就位
rep('ensureModel',
`    let res
    try {
      res = await fetch(\`\${this.profile.baseURL}/chat/completions\`, {`,
`    if (typeof this.profile.ensureModel === 'function') {
      try { await this.profile.ensureModel(options.model) } catch (e) { console.error('[dsh-ninfer-local] ensureModel:', e && e.message) }
    }

    let res
    try {
      res = await fetch(\`\${this.profile.baseURL}/chat/completions\`, {`)

// 3) effort → chat_template_kwargs.enable_thinking
rep('enable_thinking',
`      body.reasoning_effort = eff
    }`,
`      body.reasoning_effort = eff
      body.chat_template_kwargs = { ...(body.chat_template_kwargs || {}), enable_thinking: eff !== 'none' }
    }`)

// 4) 9B：--no-thinking 只在 effort=none 时保留
rep('9b quiet',
`      const eargs = [model.path,
        '--max-context', String(prof.maxContext ?? params.maxContext),
        '--port', String(params.port)]
      for (const a of prof.extraArgs ?? []) eargs.push(a)`,
`      const eargs = [model.path,
        '--max-context', String(prof.maxContext ?? params.maxContext),
        '--port', String(params.port)]
      const stopEffort = String(params.reasoningEffort ?? '')
      for (const a of prof.extraArgs ?? []) {
        // --no-thinking 只在 effort=none 时加；否则保留思考通道（由 enable_thinking 控制）
        if (a === '--no-thinking' && stopEffort && stopEffort !== 'none') continue
        eargs.push(a)
      }`)

// 5) adapter 回调：目录 + ensureModel
rep('callbacks',
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
      // 选择器里同时给出 27B 与 9B 全部模型，名字后缀标档位
      modelCatalog: () => {
        try {
          return manager.listModels().map((m) => ({
            id: m.file.replace(/\\.ninfer$/i, ''),
            name: m.file.replace(/\\.ninfer$/i, '') + ' · ' + (ENGINE_PROFILES[m.profile]?.label ?? m.profile) +
              ' (' + (m.bytes / 2 ** 30).toFixed(2) + ' GiB)',
          }))
        } catch { return [] }
      },
      // 选中的模型与当前引擎不一致 → 切档位/模型并重启；已一致则只在没跑时拉起
      ensureModel: async (modelId) => {
        const want = String(modelId || '')
        if (!want) return
        const hit = manager.listModels().find((m) => m.file.replace(/\\.ninfer$/i, '') === want)
        if (!hit) return
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
