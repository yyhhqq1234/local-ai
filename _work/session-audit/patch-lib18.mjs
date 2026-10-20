// 修 B2：重复检测要用 DSH 原始 messages（OpenAI 转换后 tool_call 在 msg.tool_calls，不在 content）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const before = s
const FROM = '      const notice = detectRepeatedToolCalls(messages)'
const TO = '      const notice = detectRepeatedToolCalls(options.messages)'
const n = s.split(FROM).length - 1
if (n !== 1) throw new Error('anchor matched ' + n)
s = s.replace(FROM, TO)
fs.writeFileSync(P + '.bak-think18', before)
fs.writeFileSync(P, s)
console.log('patched detectRepeatedToolCalls source (options.messages)')
