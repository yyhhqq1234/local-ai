import { readdirSync } from 'node:fs'
const base = 'D:/BaiduNetdiskDownload/Local-AI'
const top = readdirSync(base)
console.log('top entries matching tools:', top.filter((n) => /tool/i.test(n)).map((n) => JSON.stringify(n)))
const tools = readdirSync(base + '/_tools')
console.log('_tools entries:', tools.map((n) => JSON.stringify(n)).join(' '))
try {
  const apps = readdirSync(base + '/_tools/ninfer-build')
  console.log('ninfer-build entries:', apps.map((n) => JSON.stringify(n)).join(' '))
} catch (e) { console.log('ninfer-build ERR', e.code) }
try {
  const apps = readdirSync(base + '/_tools/infer-build')
  console.log('infer-build entries:', apps.map((n) => JSON.stringify(n)).join(' '))
} catch (e) { console.log('infer-build ERR', e.code) }
