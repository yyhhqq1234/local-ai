// 改裁剪策略：不再"头60%+尾40%"硬切（会把 system 切碎导致模型退化出乱码）
// 改为结构化压缩：① 去掉 <available_skills> 大纲 ② 段落去重 ③ 仍超才从尾部截断（保头）
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

rep('compressSystem',
`/**
 * 把 messages 裁到预算内：system 全保留，其余从最新往回填。
 * 超预算时丢弃最旧的对话消息（并插入一条说明，避免模型困惑）。
 */`,
`/**
 * system 压缩（按"信息量"删，不硬切）：
 *  1) 去掉 <available_skills> 目录块（技能可按需用 skill 工具加载，占位即可）
 *  2) 段落级去重（同一段约定被注入多次时只留一份）
 *  3) 仍超预算 → 从尾部截断（保住开头的身份与硬规则）
 * 说明：早先的"头 60% + 尾 40%"硬切会把 system 切碎，实测导致 9B 输出乱码。
 */
function compressSystem(text, budgetChars) {
  let t = String(text ?? '')
  t = t.replace(/<available_skills>[\\s\\S]*?<\\/available_skills>/g,
    '[技能目录已省略：共 N 个技能，需要时用 skill 工具按名加载]')
  const paras = t.split(/\\n{2,}/)
  const seen = new Set()
  const kept = []
  for (const p of paras) {
    const key = p.slice(0, 80).replace(/\\s+/g, ' ').trim()
    if (key && seen.has(key)) continue
    if (key) seen.add(key)
    kept.push(p)
  }
  t = kept.join('\\n\\n')
  if (t.length > budgetChars) {
    t = t.slice(0, Math.max(500, budgetChars)) +
      '\\n\\n[... system 尾部因本地引擎上下文预算（' + budgetChars + ' 字符）被截断 ...]'
  }
  return t
}

/**
 * 把 messages 裁到预算内：system 先做结构化压缩，其余从最新往回填。
 * 超预算时丢弃最旧的对话消息（并插入一条说明，避免模型困惑）。
 */`)

// 替换 system 超预算那段硬切逻辑
rep('system hard-cut',
`  // system 自己就超预算（DSH 的约定段实测 35K 字符 ≈ 20K tokens > 16K 窗口）：
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
  }`,
`  // system 自己就超预算（DSH 的约定段实测 35K 字符 ≈ 20K tokens > 16K 窗口）
  const sysBudget = Math.max(1024, Math.floor(budgetTokens * 0.85))
  if (sysTokens > sysBudget) {
    const budgetChars = Math.floor(sysBudget * 1.7)
    sys = sys.map((m) => (
      m.role === 'system' && typeof m.content === 'string'
        ? { role: 'system', content: compressSystem(m.content, budgetChars) }
        : m
    ))
    sysTokens = sys.reduce((a, m) => a + estimateTokens(m.content), 0)
    console.error('[dsh-ninfer-local] system 超预算，结构化压缩到 ≈' + sysTokens + ' tokens')
  }`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
