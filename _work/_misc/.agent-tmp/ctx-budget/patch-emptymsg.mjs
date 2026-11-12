// 修 bug：trimToBudget 无裁剪时返回同一个数组引用，回写时"先清空再遍历自身"→ 消息全丢
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

rep('early return copy',
`  if (used <= budgetTokens) return { messages, dropped: 0 }`,
`  if (used <= budgetTokens) return { messages: messages.slice(), dropped: 0 }`)

rep('apply snapshot',
`      const trimmed = trimToBudget(messages, promptBudget)
      // 注意：即使没丢消息，system 也可能被压缩过 —— 必须无条件回写，否则 body 还是原样
      messages.length = 0
      for (const m of trimmed.messages) messages.push(m)`,
`      const trimmed = trimToBudget(messages, promptBudget)
      // 注意：即使没丢消息，system 也可能被压缩过 —— 必须无条件回写，否则 body 还是原样。
      // 且必须先快照：无裁剪时 trimmed.messages 与 messages 是同一数组，清空后再遍历会得到空。
      const nextMessages = trimmed.messages === messages ? messages.slice() : trimmed.messages
      messages.length = 0
      for (const m of nextMessages) messages.push(m)`)
fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
