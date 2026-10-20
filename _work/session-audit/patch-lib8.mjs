// 修复工具块 index 冲突：reasoning 块也占 0，tool-call 块必须排在已用块之后
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s

const FROM = [
  '    for (const [id, c] of toolCalls) {',
  '      const tIdx = toolIndexById.get(id) ?? 0',
  "      yield { type: 'block-end', index: (textStarted ? 1 : 0) + tIdx, block: { type: 'tool-call', id, name: c.name, arguments: c.args } }",
  '    }',
].join(NL)

const TO = [
  '    // 块序号：reasoning 占 0，text 占其后；tool-call 依次接在已用块之后，避免 index 撞车',
  '    let blockBase = 0',
  '    if (reasoningStarted) blockBase++',
  '    if (textStarted) blockBase++',
  '    for (const [id, c] of toolCalls) {',
  '      const tIdx = toolIndexById.get(id) ?? 0',
  "      yield { type: 'block-end', index: blockBase + tIdx, block: { type: 'tool-call', id, name: c.name, arguments: c.args } }",
  '    }',
].join(NL)

const n = s.split(FROM).length - 1
if (n !== 1) throw new Error('anchor matched ' + n + ' times')
s = s.replace(FROM, TO)
fs.writeFileSync(P + '.bak-think8', before)
fs.writeFileSync(P, s)
console.log('patched tool-block-base | delta bytes', s.length - before.length)
