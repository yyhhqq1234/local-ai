// 临时调试：在 fetch 前打印 messages / body.messages 长度
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = `    let res
    try {
      res = await fetch(\`\${this.profile.baseURL}/chat/completions\`, {`
const to = `    console.error('[dbg] messages.length=' + messages.length + ' body.messages.length=' +
      (Array.isArray(body.messages) ? body.messages.length : 'n/a') +
      ' same=' + (body.messages === messages))
    let res
    try {
      res = await fetch(\`\${this.profile.baseURL}/chat/completions\`, {`
const n = s.split(from).length - 1
if (n !== 1) throw new Error('anchor=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('debug line added')
