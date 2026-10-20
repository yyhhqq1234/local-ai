// stats 增加 effort 字段，便于核对思考档是否按上限生效
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const FROM = 'systemChars, totalChars, sample: sampleKind, payloadBytes'
const TO = 'systemChars, totalChars, sample: sampleKind, effort: body.reasoning_effort || "", payloadBytes'
const n = s.split(FROM).length - 1
if (n !== 1) throw new Error('anchor matched ' + n)
s = s.replace(FROM, TO)
fs.writeFileSync(P, s)
console.log('patched stats effort field')
