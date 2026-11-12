// 9B 专用：极简 system + 小预算（大 system 会把它推到训练分布外 → 退化乱码）
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

// 1) 档位预算收小 + 打开 compactSystem
rep('profile budget',
`    maxContext: 16384,
    contextBudget: { window: 16384, maxOutput: 2048, reserve: 512 },`,
`    maxContext: 16384,
    // 实测（2026-11-09）：9B 一旦吃到大段 system/长文就退化出乱码（两代产物都复现），
    // 因此 9B 走「极简 system + 小预算 + 只带最近几轮」，把输入压回它的训练分布内。
    contextBudget: { window: 16384, maxOutput: 1024, reserve: 256 },
    compactSystem: true,
    compactSystemText: '你是石井，本地工作区执行层。中文、简短、直接；先给结论后给理由。',
    compactHistoryMessages: 6,`)

// 2) stream(): compactSystem 生效——替换 system、只留最近若干条
rep('compact apply',
`    const budget = typeof this.profile.contextBudget === 'function'
      ? this.profile.contextBudget()
      : this.profile.contextBudget`,
`    const budget = typeof this.profile.contextBudget === 'function'
      ? this.profile.contextBudget()
      : this.profile.contextBudget
    if (this.profile.compactSystem) {
      const keepN = Number(this.profile.compactHistoryMessages) || 6
      const sysText = String(this.profile.compactSystemText || '你是助手，用中文简短回答。')
      const rest = messages.filter((m) => m.role !== 'system')
      const kept = rest.slice(-keepN)
      messages.length = 0
      messages.push({ role: 'system', content: sysText })
      for (const m of kept) messages.push(m)
      console.error('[dsh-ninfer-local] 9B compact: system 精简为 ' + sysText.length +
        ' 字符，历史保留最近 ' + kept.length + '/' + rest.length + ' 条')
    }`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
