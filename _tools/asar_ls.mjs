// 读 app.asar 头部索引，列出 dsh/node_modules/@deepseek-ai/* 包名（含 lib 入口是否存在）
import { openSync, readSync, closeSync } from 'node:fs'

const ASAR = 'C:\\Users\\Administrator\\AppData\\Local\\Programs\\DeepSeek Harness\\resources\\app.asar'
const fd = openSync(ASAR, 'r')
const head = Buffer.alloc(16)
readSync(fd, head, 0, 16, 0)

// asar: 4B uint32(=4) 4B pickle size 4B json size 4B json len(?) —— 实际：
// [0..4) = 4 (uint32), [4..8) = header pickle size, [8..12) = json string size, [12..16) = json len
const jsonLen = head.readUInt32LE(12)
const buf = Buffer.alloc(jsonLen)
readSync(fd, buf, 0, jsonLen, 16)
closeSync(fd)
const idx = JSON.parse(buf.toString('utf8'))

const target = ['dsh', 'node_modules', '@deepseek-ai']
let node = idx.files
for (const t of target) {
  node = node?.[t]?.files
  if (!node) { console.log('missing path segment:', t); process.exit(1) }
}
const names = Object.keys(node).sort()
console.log(`@deepseek-ai 包数 = ${names.length}`)
const want = ['dsh-tools', 'dsh-agent', 'dsh-system-prompt', 'dsh-scope', 'dsh-llm', 'schemastery', 'cosmokit']
for (const n of names) {
  const hasLib = !!(node[n].files?.lib?.files?.['index.js'] || node[n].files?.['lib']?.files?.['index.mjs'])
  if (want.includes(n) || n.includes('scope') || n.includes('prompt') || n.includes('tool')) {
    const pkg = node[n].files?.['package.json']
    console.log(`  ${n}  lib/index.js=${hasLib ? 'Y' : 'N'}  files=${Object.keys(node[n].files ?? {}).join(',')}`)
  }
}
console.log('\n--- 全量名单 ---')
console.log(names.join(' '))
