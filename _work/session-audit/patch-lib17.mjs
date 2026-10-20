// B2：检测重复工具调用（同工具+近似参数 ≥3 次）→ 注入打断提示
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to); done.push(name)
}

// 1) 在 executionRules 注入之后追加重复检测
rep('b2-inject',
  '    if (this.profile.executionRules) {',
  '    if (this.profile.detectRepeatToolCalls !== false) {' + NL +
  '      const notice = detectRepeatedToolCalls(messages)' + NL +
  '      if (notice) {' + NL +
  "        const sysMsg2 = messages.find((m) => m.role === 'system' && typeof m.content === 'string')" + NL +
  '        if (sysMsg2) sysMsg2.content = sysMsg2.content + String.fromCharCode(10) + String.fromCharCode(10) + notice' + NL +
  "        else messages.unshift({ role: 'system', content: notice })" + NL +
  '      }' + NL +
  '    }' + NL +
  '    if (this.profile.executionRules) {')

// 2) 配置开关
rep('b2-cfg',
  '  offloadToolResultMaxChars: 1200,',
  '  detectRepeatToolCalls: true,   // 同工具+近似参数连续 3 次 → 注入打断提示' + NL +
  '  offloadToolResultMaxChars: 1200,')

// 3) 传参
rep('b2-ctor',
  '      offloadToolResultMaxChars: cfg.offloadToolResultMaxChars,',
  '      detectRepeatToolCalls: cfg.detectRepeatToolCalls,' + NL +
  '      offloadToolResultMaxChars: cfg.offloadToolResultMaxChars,')

// 4) 实现
const impl = [
  'function detectRepeatedToolCalls(messages) {',
  '  const calls = []',
  '  for (const m of messages) {',
  "    if (m.role !== 'assistant' || !Array.isArray(m.content)) continue",
  '    for (const b of m.content) {',
  "      if (b && b.type === 'tool-call') calls.push((b.name || '') + '|' + String(b.arguments || '').slice(0, 140))",
  '    }',
  '  }',
  '  const recent = calls.slice(-12)',
  '  const freq = new Map()',
  '  for (const k of recent) freq.set(k, (freq.get(k) || 0) + 1)',
  '  let worst = null',
  '  for (const [k, n] of freq) if (n >= 3 && (!worst || n > worst.n)) worst = { k, n }',
  '  if (!worst) return null',
  '  const name = worst.k.split("|")[0]',
  '  return "## 重复调用警告（自动检测）" + String.fromCharCode(10) +',
  '    "你已用几乎相同的参数调用 " + name + " " + worst.n + " 次，且没有进展。" + String.fromCharCode(10) +',
  '    "请立即停止重试同一操作，改为：①说明当前阻塞点与已尝试过的路径 ②请求用户决策 或 ③换一种完全不同的策略（只允许一次）。"',
  '}',
].join(NL)

rep('b2-impl', 'function toOpenAITools(tools) {', impl + NL + NL + 'function toOpenAITools(tools) {')

fs.writeFileSync(P + '.bak-think17', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
