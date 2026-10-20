// 空转检测升级：不只看"完全相同参数"，而是看①参数结构重复 ②连续失败率 ③单轮调用总量
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

// 1) 换实现：detectRepeatedToolCalls → detectStuckLoop（保留旧名做别名）
const FROM_START = 'function detectRepeatedToolCalls(messages) {'
const implStart = s.indexOf(FROM_START)
if (implStart < 0) throw new Error('detectRepeatedToolCalls not found')
const implEnd = s.indexOf(NL + '}' + NL, implStart)
if (implEnd < 0) throw new Error('impl end not found')
const oldImpl = s.slice(implStart, implEnd + NL.length + 1)

const newImpl = [
  'function detectRepeatedToolCalls(messages) {',
  '  const calls = []',
  '  const results = []',
  '  for (const m of messages || []) {',
  '    if (m.role === \'assistant\' && Array.isArray(m.content)) {',
  '      for (const b of m.content) if (b && b.type === \'tool-call\') calls.push(b)',
  '    }',
  '    if (m.role === \'tool\' && Array.isArray(m.content)) {',
  '      const t = m.content.map((x) => (x && x.text) || \'\').join(\' \')',
  '      if (t) results.push(t)',
  '    }',
  '  }',
  '  if (!calls.length) return null',
  '  const notices = []',
  '  // A) 参数结构重复（同工具 + 相同的参数键集合），≥3 次即判空转',
  '  const sigOf = (c) => {',
  '    let o = {}',
  '    try { o = JSON.parse(String(c.arguments || \'{}\')) } catch (e) { o = {} }',
  '    return String(c.name || \'\') + \'|\' + Object.keys(o).sort().join(\',\')',
  '  }',
  '  const freq = new Map()',
  '  for (const c of calls.slice(-12)) { const k = sigOf(c); freq.set(k, (freq.get(k) || 0) + 1) }',
  '  let worst = null',
  '  for (const [k, n] of freq) if (n >= 3 && (!worst || n > worst.n)) worst = { k, n }',
  '  if (worst) {',
  '    notices.push(\'你已用相同的参数结构调用 \' + worst.k.split(\'|\')[0] + \' \' + worst.n + \' 次（只换了字段值）。换写法不改变结果。\')',
  '  }',
  '  // B) 连续失败率：最近 12 条工具结果里失败词 ≥4 条',
  '  const failRe = new RegExp(\'(error|failed|invalid|must be|cannot|not found|exceed|denied|失败|错误|非法|必须|不允许)\', \'i\')',
  '  const lastR = results.slice(-12)',
  '  const fails = lastR.filter((t) => failRe.test(t)).length',
  '  if (lastR.length >= 4 && fails >= 4) {',
  '    notices.push(\'最近 \' + lastR.length + \' 次工具结果里有 \' + fails + \' 次报错，说明当前路径走不通。\')',
  '  }',
  '  // C) 单轮调用总量超标',
  '  if (calls.length >= 15 && notices.length === 0) {',
  '    notices.push(\'本轮已调用工具 \' + calls.length + \' 次，接近失控；请收敛。\')',
  '  }',
  '  if (!notices.length) return null',
  '  return \'## 空转告警（自动检测）\' + String.fromCharCode(10) +',
  '    notices.map((x) => \'- \' + x).join(String.fromCharCode(10)) + String.fromCharCode(10) +',
  '    \'立即按顺序处理，不要再试参数：\' + String.fromCharCode(10) +',
  '    \'1) 目标已达成 → 马上收尾（kitty_settings action=task-close，或直接回答用户）\' + String.fromCharCode(10) +',
  '    \'2) 卡在参数格式 → 用工具自带的说明类工具查一次正确字段（如 kitty_ops），只试一次\' + String.fromCharCode(10) +',
  '    \'3) 仍失败 → 停止重试，向用户汇报：已完成什么 / 卡在哪 / 需要什么\'',
  '}',
].join(NL)

s = s.slice(0, implStart) + newImpl + s.slice(implEnd + NL.length + 1)
done.push('rewrite-detectStuckLoop')

fs.writeFileSync(P + '.bak-think24', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
