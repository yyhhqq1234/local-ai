// system 单独超预算时也要压：保留头 60% + 尾 40%，中间插标记
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = `  const sys = messages.filter((m) => m.role === 'system')
  const rest = messages.filter((m) => m.role !== 'system')
  let sysTokens = 0
  for (const m of sys) sysTokens += estimateTokens(typeof m.content === 'string' ? m.content : '')
  let room = budgetTokens - sysTokens`
const to = `  let sys = messages.filter((m) => m.role === 'system')
  const rest = messages.filter((m) => m.role !== 'system')
  let sysTokens = 0
  for (const m of sys) sysTokens += estimateTokens(typeof m.content === 'string' ? m.content : '')

  // system 自己就超预算（DSH 的约定段实测 35K 字符 ≈ 20K tokens > 16K 窗口）：
  // 按字符保头 60% / 尾 40% 压到预算的 85%，并在中间标注被截断。
  const sysBudget = Math.max(1024, Math.floor(budgetTokens * 0.85))
  if (sysTokens > sysBudget) {
    const keepChars = Math.floor(sysBudget * 1.7)
    const totalChars = sys.reduce((a, m) => a + (typeof m.content === 'string' ? m.content.length : 0), 0)
    const ratio = totalChars > 0 ? keepChars / totalChars : 1
    sys = sys.map((m) => {
      const text = typeof m.content === 'string' ? m.content : ''
      if (!text) return m
      const share = Math.max(200, Math.floor(text.length * ratio))
      if (share >= text.length) return m
      const head = Math.floor(share * 0.6)
      const tail = share - head
      return {
        role: 'system',
        content: text.slice(0, head) +
          '\\n\\n[... system 提示词因本地引擎上下文预算（' + budgetTokens + ' tokens）被截断 ' +
          (text.length - share) + ' 字符 ...]\\n\\n' +
          (tail > 0 ? text.slice(text.length - tail) : ''),
      }
    })
    sysTokens = sys.reduce((a, m) => a + estimateTokens(m.content), 0)
    console.error('[dsh-ninfer-local] system 超预算，已压缩到 ≈' + sysTokens + ' tokens')
  }

  let room = budgetTokens - sysTokens`
const n = s.split(from).length - 1
if (n !== 1) throw new Error('anchor count=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('patched system-trim')
