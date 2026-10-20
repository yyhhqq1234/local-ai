// 空转硬熔断：同结构调用 ≥6 或连续失败 ≥6 时，不再请求模型，直接终止本轮
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

// 1) 配置
rep('cfg-breaker',
  '  detectRepeatToolCalls: true,',
  '  detectRepeatToolCalls: true,' + NL +
  '  stuckBreaker: true,        // 空转硬熔断：同结构≥6 或连续失败≥6 时直接终止本轮，不再请求模型')

// 2) 传参
rep('ctor-breaker',
  '      detectRepeatToolCalls: cfg.detectRepeatToolCalls,',
  '      detectRepeatToolCalls: cfg.detectRepeatToolCalls,' + NL +
  '      stuckBreaker: cfg.stuckBreaker,')

// 3) 抽出统计函数 + 熔断（在 stream 开头的 messages 构造之后）
rep('assess-impl',
  'function detectRepeatedToolCalls(messages) {',
  'function assessStuck(messages) {' + NL +
  '  const calls = []' + NL +
  '  const results = []' + NL +
  '  for (const m of messages || []) {' + NL +
  "    if (m.role === 'assistant' && Array.isArray(m.content)) {" + NL +
  "      for (const b of m.content) if (b && b.type === 'tool-call') calls.push(b)" + NL +
  '    }' + NL +
  "    if (m.role === 'tool' && Array.isArray(m.content)) {" + NL +
  "      const t = m.content.map((x) => (x && x.text) || '').join(' ')" + NL +
  '      if (t) results.push(t)' + NL +
  '    }' + NL +
  '  }' + NL +
  '  const sigOf = (c) => {' + NL +
  '    let o = {}' + NL +
  "    try { o = JSON.parse(String(c.arguments || '{}')) } catch (e) { o = {} }" + NL +
  "    return String(c.name || '') + '|' + Object.keys(o).sort().join(',')" + NL +
  '  }' + NL +
  '  const freq = new Map()' + NL +
  '  for (const c of calls.slice(-16)) { const k = sigOf(c); freq.set(k, (freq.get(k) || 0) + 1) }' + NL +
  '  let maxSig = 0, maxSigName = ""' + NL +
  '  for (const [k, n] of freq) if (n > maxSig) { maxSig = n; maxSigName = k.split("|")[0] }' + NL +
  "  const failRe = new RegExp('(error|failed|invalid|must be|cannot|not found|exceed|denied|失败|错误|非法|必须|不允许)', 'i')" + NL +
  '  const lastR = results.slice(-16)' + NL +
  '  const fails = lastR.filter((t) => failRe.test(t)).length' + NL +
  '  return { calls: calls.length, maxSig, maxSigName, results: lastR.length, fails }' + NL +
  '}' + NL + NL +
  'function detectRepeatedToolCalls(messages) {')

// 3b) 熔断逻辑：插在 tools 过滤之前（构造 body 之后、发请求之前）
rep('breaker-check',
  '    let sampleKind = ""',
  '    if (this.profile.stuckBreaker !== false) {' + NL +
  '      const st = assessStuck(options.messages)' + NL +
  '      if (st.maxSig >= 6 || st.fails >= 6) {' + NL +
  "        const msg = '[空转熔断] 本轮已连续 ' + st.maxSig + ' 次同结构调用（' + st.maxSigName + '）与 ' + st.fails + ' 次工具报错，判定为无效循环，已强制终止，避免继续消耗。请给出新指示或换一种任务拆法。'" + NL +
  "        yield { type: 'block-start', index: 0, blockType: 'text' }" + NL +
  "        yield { type: 'text-delta', index: 0, text: msg }" + NL +
  "        yield { type: 'block-end', index: 0, block: { type: 'text', text: msg } }" + NL +
  "        yield { type: 'finish', reason: { kind: 'stop' } }" + NL +
  '        return' + NL +
  '      }' + NL +
  '    }' + NL +
  '    let sampleKind = ""')

fs.writeFileSync(P + '.bak-think25', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
