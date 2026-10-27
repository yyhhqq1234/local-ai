// 空转熔断回归：v1（旧判据） vs v2（现行 lib/index.js 导出）对照
// 跑法：node D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\test-stuck-breaker.mjs
import { assessStuck as v2 } from '../../plugins/dsh-ninfer-local/lib/index.js'

// ── v1 参考实现（旧版原文，仅用于对照误杀） ──────────────────────────────
function v1(messages) {
  const calls = [], results = []
  for (const m of messages || []) {
    if (m.role === 'assistant' && Array.isArray(m.content)) {
      for (const b of m.content) if (b && b.type === 'tool-call') calls.push(b)
    }
    if (m.role === 'tool' && Array.isArray(m.content)) {
      const t = m.content.map((x) => (x && x.text) || '').join(' ')
      if (t) results.push(t)
    }
  }
  const sigOf = (c) => {
    let o = {}
    try { o = JSON.parse(String(c.arguments || '{}')) } catch { o = {} }
    return String(c.name || '') + '|' + Object.keys(o).sort().join(',')
  }
  const freq = new Map()
  for (const c of calls.slice(-16)) { const k = sigOf(c); freq.set(k, (freq.get(k) || 0) + 1) }
  let maxSig = 0, maxSigName = ''
  for (const [k, n] of freq) if (n > maxSig) { maxSig = n; maxSigName = k.split('|')[0] }
  const failRe = new RegExp('(error|failed|invalid|must be|cannot|not found|exceed|denied|失败|错误|非法|必须|不允许)', 'i')
  const lastR = results.slice(-16)
  const fails = lastR.filter((t) => failRe.test(t)).length
  return { calls: calls.length, maxSig, maxSigName, fails, tripped: (maxSig >= 6 || fails >= 6) }
}

// ── 构造器 ────────────────────────────────────────────────────────────────
const call = (name, args) => ({ role: 'assistant', content: [{ type: 'tool-call', id: 'c' + Math.random(), name, arguments: JSON.stringify(args) }] })
const tool = (text) => ({ role: 'tool', content: [{ type: 'text', text }] })
const seq = (pairs) => pairs.flatMap(([n, a, r]) => [call(n, a), tool(r)])

const cases = []

// A 正常长任务：读 6 个不同文件 + 跑 6 条不同命令 + grep 4 次（旧版必误杀）
cases.push({
  name: 'A 正常长任务(异参同工具)',
  expect: false,
  msgs: seq([
    ...Array.from({ length: 6 }, (_, i) => ['read', { file_path: `F:/w/f${i}.md`, limit: 200 }, `# f${i} 内容正常`]),
    ...Array.from({ length: 6 }, (_, i) => ['ops_bash', { command: `echo step${i}`, description: `step ${i}` }, `step${i}`]),
    ...Array.from({ length: 4 }, (_, i) => ['grep', { pattern: `PAT${i}`, path: 'F:/w' }, 'no match']),
  ]),
})

// B 真空转：同一工具同一参数连续 6 次（v2 必须熔断）
cases.push({
  name: 'B 真空转(同参连续6次)',
  expect: true,
  msgs: seq(Array.from({ length: 6 }, () => ['kitty_settings', { action: 'task-close' }, 'ERR|EARLY-EXIT-DENY'])),
})

// C 尾部连续硬报错 6 次（不同工具也算，v2 熔断）
cases.push({
  name: 'C 连续硬报错(尾部6条)',
  expect: true,
  msgs: seq(Array.from({ length: 6 }, (_, i) => [`tool${i}`, { x: i }, 'ERR|SOME-CODE 非法参数'])),
})

// D 日志噪音：16 条工具结果里 8 条正文含 error/失败 字样，但全部正常返回（旧版误杀）
cases.push({
  name: 'D 日志噪音(含 error 字样)',
  expect: false,
  msgs: seq(Array.from({ length: 16 }, (_, i) => [
    'ops_bash',
    { command: `tail -n 5 log${i}.txt`, description: 'tail log' },
    i % 2 === 0 ? `[2026-10-27] 0 errors, 0 failed, 无失败记录, exit code: 0` : `line ok ${i}`,
  ])),
})

// E 同工具异值 8 次（旧版按"键集合"计 8 次直接熔断，v2 不算重复）
cases.push({
  name: 'E 同工具异值8次',
  expect: false,
  msgs: seq(Array.from({ length: 8 }, (_, i) => ['edit', { file_path: `F:/w/x${i}.js`, old_string: `a${i}`, new_string: `b${i}` }, 'ok'])),
})

// F 探针中途单次失败（不该熔断）
cases.push({
  name: 'F 偶发失败(非连续)',
  expect: false,
  msgs: seq([
    ['read', { file_path: 'F:/w/a.txt' }, 'ok'],
    ['ops_bash', { command: 'bad cmd', description: 'oops' }, '[exit code: 1] not found'],
    ['read', { file_path: 'F:/w/b.txt' }, 'ok'],
    ['grep', { pattern: 'x', path: 'F:/w' }, 'no match'],
    ['write', { file_path: 'F:/w/c.txt', content: 'x' }, 'ok'],
    ['read', { file_path: 'F:/w/c.txt' }, 'x'],
  ]),
})

let bad = 0
const rows = []
for (const c of cases) {
  const a = v1(c.msgs)
  const b = v2(c.msgs)
  const ok = b.tripped === c.expect
  if (!ok) bad++
  rows.push({
    用例: c.name,
    期望: c.expect ? '熔断' : '放行',
    'v1(旧)': `${a.tripped ? '熔断' : '放行'} (maxSig=${a.maxSig},fails=${a.fails})`,
    'v2(新)': `${b.tripped ? '熔断' : '放行'} (tailRun=${b.tailRun},errStreak=${b.errStreak},why=${b.why || '-'})`,
    结果: ok ? 'PASS' : 'FAIL',
  })
}
console.table(rows)
console.log(bad === 0 ? `\n全部通过 ${cases.length}/${cases.length}` : `\n失败 ${bad}/${cases.length}`)
process.exit(bad === 0 ? 0 : 1)
