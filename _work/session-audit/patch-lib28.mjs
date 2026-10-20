// 规则 8 修正：kitty 收尾是两步状态机（dispatch{finish|abandon} → close），直接 close 会被 EARLY-EXIT-DENY 拒
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const before = s
const OLD = '8) kitty 任务态收尾（必做，一次到位）：进任务态用 kitty_settings action=target-set；收尾只允许 action=task-close（taskTransition 写 state=completed 或 abandoned）。task-close 返回成功后立即结束本轮，不要再调 task-dispatch、task-get 或重复 task-close（它们改不了终态，只会空转）。'
const NEW = '8) kitty 任务态收尾（两步，顺序不能跳）：先 kitty_settings action=task-dispatch，带 taskGeneration 与 taskTransition={"state":"finish"}（放弃用 "abandon"）；再 action=task-close，taskTransition={"state":"completed"}。直接 task-close 会被 ERR|EARLY-EXIT-DENY 拒绝（必须先 finish/abandon）。收到 ERR|Cannot read properties of undefined 说明 taskTransition 结构不对，停下来查 kitty_ops 或直接向用户汇报，不要换参数硬试。收尾成功后立即停止。'
const n = s.split(OLD).length - 1
if (n !== 1) throw new Error('anchor matched ' + n)
s = s.replace(OLD, NEW)
fs.writeFileSync(P + '.bak-think28', before)
fs.writeFileSync(P, s)
console.log('patched rule8 (two-step state machine) | delta bytes', s.length - before.length)
