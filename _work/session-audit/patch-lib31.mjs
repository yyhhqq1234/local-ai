// 加规则 9：错误反应对照（few-shot 式）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s

const ANCHOR = '收尾成功后立即停止。'
const RULE9 = '收尾成功后立即停止。\\n9) 错误反应的对照（照正确那一列做）：工具报 ERR|EARLY-EXIT-DENY 时，错误做法是换参数反复 task-close，正确做法是先 task-dispatch（type=finish，带 evidence）再 task-close 一次并停止；工具报 Cannot read properties of undefined 或任何看不懂的底层异常时，错误做法是换参数键名继续试，正确做法是停止重试，把现象与已完成进度汇报给用户。'
const n = s.split(ANCHOR).length - 1
if (n !== 1) throw new Error('anchor matched ' + n)
s = s.replace(ANCHOR, RULE9)
fs.writeFileSync(P + '.bak-think31b', before)
fs.writeFileSync(P, s)
console.log('patched rule 9 | delta bytes', s.length - before.length)
