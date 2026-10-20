// B1 空交付可见化 + 动态 maxTokens；B4 旁路阈值调优
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

// 1) B4：旁路阈值 2000 → 1200
rep('b4-threshold',
  '  offloadToolResultMaxChars: 2000,',
  '  offloadToolResultMaxChars: 1200,')

// 2) B1a：动态 maxTokens（长产物任务放宽预算）
rep('b1a-dynamic-maxtokens',
  '    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))',
  '    // B1a：长产物任务放宽输出预算（reasoning 常把 8192 吃光，正文写不出来）' + NL +
  '    const longAskRe = /(完整|全部|详细|长文|全文|3000\\s*字|2000\\s*字|1000\\s*字|800\\s*字|HTML|SVG|整个文件|整段代码|完整代码)/' + NL +
  '    let lastUserText = ""' + NL +
  '    for (let i = messages.length - 1; i >= 0; i--) {' + NL +
  "      if (messages[i].role !== 'user') continue" + NL +
  '      const cc = messages[i].content' + NL +
  "      lastUserText = typeof cc === 'string' ? cc : (Array.isArray(cc) ? cc.map((b) => (b && b.text) || '').join(' ') : '')" + NL +
  '      if (lastUserText) break' + NL +
  '    }' + NL +
  '    const baseMax = Number(options.maxTokens) || 8192' + NL +
  '    body.max_tokens = longAskRe.test(lastUserText) ? Math.max(baseMax, 16384) : baseMax' + NL +
  '    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))')

// 3) B1b：只有思考没有正文 —— 补一条可见说明，避免"空白回复"
rep('b1b-empty-notice',
  '    if (reasoningStarted && !textStarted) {' + NL +
  "      yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: reasonBuf } }" + NL +
  '    }',
  '    // B1b：被 max_tokens 截断且正文为空时，给出可见提示（否则前端表现为空白回复）' + NL +
  "    if (!textStarted && finish === 'length' && reasonBuf.length > 0) {" + NL +
  '      textStarted = true' + NL +
  '      textIndex = reasoningStarted ? 1 : 0' + NL +
  "      yield { type: 'block-start', index: textIndex, blockType: 'text' }" + NL +
  "      textBuf = '[本轮只产出思考，正文被 max_tokens 截断；建议重发或把任务拆小]'" + NL +
  "      yield { type: 'text-delta', index: textIndex, text: textBuf }" + NL +
  '    }' + NL +
  '    if (reasoningStarted && !textStarted) {' + NL +
  "      yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: reasonBuf } }" + NL +
  '    }')

fs.writeFileSync(P + '.bak-think16', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
