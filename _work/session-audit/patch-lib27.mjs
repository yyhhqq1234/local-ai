// 严重修复：熔断用 finish=stop 不会终止 DSH 的 agent loop（实测 1044 步重复同一句熔断文本）
// 改法：熔断必须用 finish kind=error，DSH 才会终止本轮
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const before = s
const NL = String.fromCharCode(10)

const FROM = [
  "        yield { type: 'block-end', index: 0, block: { type: 'text', text: msg } }",
  "        yield { type: 'finish', reason: { kind: 'stop' } }",
  '        return',
].join(NL)

const TO = [
  "        yield { type: 'block-end', index: 0, block: { type: 'text', text: msg } }",
  '        // 必须用 error 终止：stop 会被 agent loop 当成“话说完但任务没完”，继续开下一步（实测 1044 步死循环）',
  "        yield { type: 'finish', reason: { kind: 'error', failure: { message: 'STUCK_LOOP', code: 'STUCK_LOOP' } } }",
  '        return',
].join(NL)

const n = s.split(FROM).length - 1
if (n !== 1) throw new Error('anchor matched ' + n)
s = s.replace(FROM, TO)

fs.writeFileSync(P + '.bak-think27', before)
fs.writeFileSync(P, s)
console.log('patched breaker finish: stop -> error | delta bytes', s.length - before.length)
