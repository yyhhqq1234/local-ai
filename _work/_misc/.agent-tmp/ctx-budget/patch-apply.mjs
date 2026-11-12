// 修 bug：system 被压缩但 dropped=0 时没有回写 messages（导致仍发原样 25200 字符）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = `      const trimmed = trimToBudget(messages, promptBudget)
      if (trimmed.dropped > 0) {
        messages.length = 0
        for (const m of trimmed.messages) messages.push(m)
        console.error('[dsh-ninfer-local] 裁剪历史 ' + trimmed.dropped + ' 条（预算 ' + promptBudget + ' tokens）')
      }`
const to = `      const trimmed = trimToBudget(messages, promptBudget)
      // 注意：即使没丢消息，system 也可能被压缩过 —— 必须无条件回写，否则 body 还是原样
      messages.length = 0
      for (const m of trimmed.messages) messages.push(m)
      if (trimmed.dropped > 0) {
        console.error('[dsh-ninfer-local] 裁剪历史 ' + trimmed.dropped + ' 条（预算 ' + promptBudget + ' tokens）')
      }`
const n = s.split(from).length - 1
if (n !== 1) throw new Error('anchor count=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('patched: unconditional apply')
