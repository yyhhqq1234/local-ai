// 强化规则 8：收尾只许 task-close，且成功后立即停（会话 3197072f 里模型试了 10 次 task-dispatch）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const before = s
const OLD = '8) kitty 任务态收尾（必做）：进任务态用 kitty_settings action=target-set；目标完成或放弃时必须用 kitty_settings action=task-close（终态 completed/abandoned）。不收尾会被任务系统反复催办（表现为「任务 xxx 尚未完成 revision=N」）。'
const NEW = '8) kitty 任务态收尾（必做，一次到位）：进任务态用 kitty_settings action=target-set；收尾只允许 action=task-close（taskTransition 写 state=completed 或 abandoned）。task-close 返回成功后立即结束本轮，不要再调 task-dispatch、task-get 或重复 task-close（它们改不了终态，只会空转）。'
const n = s.split(OLD).length - 1
if (n !== 1) throw new Error('anchor matched ' + n)
s = s.replace(OLD, NEW)
fs.writeFileSync(P + '.bak-think23', before)
fs.writeFileSync(P, s)
console.log('patched rule 8 (task-close 一次到位) | delta bytes', s.length - before.length)
