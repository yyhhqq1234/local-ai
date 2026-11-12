// 引擎没起时，模型下拉不应再硬给 27B 兜底 id（会 404）；改为给"当前档位的现行模型"
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

rep('listModels dynamic fallback',
`  async listModels(provider) {
    try {
      const d = await httpJson(\`\${this.profile.baseURL}/models\`, this.profile.timeoutMs ?? 5000)
      return (d?.data ?? []).map((m) => ({ provider, id: m.id, name: m.id }))
    } catch {
      return (this.profile.fallbackModels ?? []).map((m) => ({ provider, id: m.id, name: m.name }))
    }
  }`,
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
  }`)

rep('pass activeModelId',
`      baseURL: cfg.baseURL,
      displayName: cfg.displayName,
      fallbackModels: cfg.fallbackModels,`,
`      baseURL: cfg.baseURL,
      displayName: cfg.displayName,
      fallbackModels: cfg.fallbackModels,
      activeModelId: () => {
        try {
          const f = manager.activeModelFile()
          return f ? f.replace(/\\.ninfer$/i, '') : undefined
        } catch { return undefined }
      },`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
