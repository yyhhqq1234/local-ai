// 第三轮：强制思考档（堵住 UI 选 high 覆盖引擎默认的路径，只作用于本地 provider）
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []

function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to)
  done.push(name)
}

// 1) 配置：强制档（空串=不强制，走请求值）
rep('cfg-force-effort',
  "  defaultEffort: 'minimal',",
  "  defaultEffort: 'minimal'," + NL +
  "  // 请求级强制档：非空时无视模型选择器下发的 reasoning_effort（本地 IQ2 长思考会吃光 8K 输出预算）" + NL +
  "  forceReasoningEffort: 'minimal',")

// 2) 构造传参
rep('ctor-force-effort',
  "      defaultEffort: cfg.defaultEffort,",
  "      defaultEffort: cfg.defaultEffort," + NL +
  "      forceReasoningEffort: cfg.forceReasoningEffort,")

// 3) stream：强制覆盖
rep('stream-force-effort',
  "    if (options.reasoningEffort) body.reasoning_effort = String(options.reasoningEffort)",
  "    if (this.profile.forceReasoningEffort) body.reasoning_effort = String(this.profile.forceReasoningEffort)" + NL +
  "    else if (options.reasoningEffort) body.reasoning_effort = String(options.reasoningEffort)")

fs.writeFileSync(P + '.bak-think3', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
