// 模型侧优化：把工具错误码翻译成"可直接执行的动作建议"，附在 tool 结果后面
// 目的：模型不需要从 ERR 文本里推理，照做即可（历史病历：拿到 EARLY-EXIT-DENY 后仍穷举试参数）
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
rep('cfg-errhints',
  '  stuckBreaker: true,',
  '  stuckBreaker: true,' + NL + '  errorHints: true,          // 工具返回 ERR|CODE 时，附加"建议下一步"（把错误码翻成可执行动作）')

// 2) 传参
rep('ctor-errhints',
  '      stuckBreaker: cfg.stuckBreaker,',
  '      stuckBreaker: cfg.stuckBreaker,' + NL + '      errorHints: cfg.errorHints,')

// 3) 调用（offload 之后）
rep('call-errhints',
  '    if (this.profile.executionRules) {',
  '    if (this.profile.errorHints !== false) {' + NL +
  '      annotateToolErrors(messages)' + NL +
  '    }' + NL +
  '    if (this.profile.executionRules) {')

// 4) 实现
const impl = [
  'function annotateToolErrors(messages) {',
  '  const HINTS = {',
  '    \'EARLY-EXIT-DENY\': \'先 kitty_settings action=task-dispatch（taskTransition 用 type=finish，附 evidence 数组）解锁，再 action=task-close\',',
  '    \'TASK-TRANSITION-UNKNOWN\': \'taskTransition 里字段是 type 不是 state；合法 type 有 12 种，见 kitty_settings 的 schema 说明\',',
  '    \'TASK-DISPATCH-MISSING\': \'task-dispatch 需要 taskGeneration + taskTransition，且 transition 必带 type\',',
  '    \'SESSION-KEY-MISSING\': \'先 kitty_settings action=target-set 打开会话（带 target 与 sessionGoal）\',',
  '    \'TASK-MISSING\': \'当前没有打开的任务会话；先 target-set\',',
  '    \'STUCK_LOOP\': \'本轮已被熔断，直接向用户汇报进展与阻塞点\',',
  '  }',
  '  for (const m of messages || []) {',
  "    if (m.role !== 'tool' || typeof m.content !== 'string') continue",
  "    if (m.content.indexOf('ERR|') < 0) continue",
  "    if (m.content.indexOf('[建议下一步]') >= 0) continue",
  '    const tips = []',
  '    for (const code of Object.keys(HINTS)) {',
  '      if (m.content.indexOf(code) >= 0) tips.push(code + \' → \' + HINTS[code])',
  '    }',
  '    if (!tips.length) tips.push(\'未识别的错误码：不要换参数硬试，直接向用户说明现象并请求指示\')',
  '    m.content += String.fromCharCode(10) + \'[建议下一步] \' + tips.join(\' ｜ \')',
  '  }',
  '}',
].join(NL)

rep('impl-errhints', 'function toOpenAITools(tools) {', impl + NL + NL + 'function toOpenAITools(tools) {')

fs.writeFileSync(P + '.bak-think30', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
