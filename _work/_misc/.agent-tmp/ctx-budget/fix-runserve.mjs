// 修 run-serve.ps1 的 Context 默认值（上一轮字符串替换没命中）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/_tools/run-serve.ps1'
let s = fs.readFileSync(P, 'utf8')
const before = s
s = s.replace(/\$MaxContext\s*=\s*4096/, '$MaxContext= 16384')
s = s.replace(/\[int\]\$MaxContext\s*=\s*4096/, '[int]$MaxContext = 16384')
if (s === before) {
  // 兜底：逐行处理
  s = before.split('\n').map((ln) => ln.replace('4096', '16384')).join('\n')
}
fs.writeFileSync(P, s, 'utf8')
const line = s.split('\n').find((l) => l.includes('MaxContext'))
console.log('now:', line && line.trim())
