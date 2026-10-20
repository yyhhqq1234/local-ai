// 补 kitty 门控工具：kitty_settings（进/退任务态）+ kitty_status，并在纪律里写清收尾动作
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to); done.push(name)
}

// 1) 白名单 14 → 16
rep('allow-kitty-gate',
  "'ninfer_model', 'ninfer_params', 'kitty_ce', 'kitty_ops'],",
  "'ninfer_model', 'ninfer_params', 'kitty_ce', 'kitty_ops', 'kitty_settings', 'kitty_status'],")

// 2) 纪律补第 8 条（JSON 字符串里换行是 \\n 字面）
rep('rule-task-close',
  '7) 工具输出里带「已落盘: <path>」的说明摘要已足够判断，不要立刻 read 回来；确需原始细节再读，且只读一次。',
  '7) 工具输出里带「已落盘: <path>」的说明摘要已足够判断，不要立刻 read 回来；确需原始细节再读，且只读一次。\\n8) kitty 任务态收尾（必做）：进任务态用 kitty_settings action=target-set；目标完成或放弃时必须用 kitty_settings action=task-close（终态 completed/abandoned）。不收尾会被任务系统反复催办（表现为「任务 xxx 尚未完成 revision=N」）。')

fs.writeFileSync(P + '.bak-think22', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
