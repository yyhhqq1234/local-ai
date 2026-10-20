// 模拟 system 章节去重：同名且内容完全相同的 markdown 章节只保留第一份
import fs from 'node:fs'

const L = fs.readFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/session.jsonl', 'utf8').split('\n').filter(Boolean)
const sys = JSON.parse(L[10]).data.message.content.map((b) => b.text || '').join('\n')

const NL = String.fromCharCode(10)
const lines = sys.split(NL)

// 切块：每个 ^#{1,3} 标题开始一块，块内容到下一个标题
const blocks = []
let cur = null
for (const line of lines) {
  if (/^#{1,3} /.test(line)) {
    if (cur) blocks.push(cur)
    cur = { head: line.trim(), body: [] }
  } else {
    if (!cur) { cur = { head: '', body: [] } }
    cur.body.push(line)
  }
}
if (cur) blocks.push(cur)

const norm = (s) => s.replace(/\s+/g, ' ').trim()
const seen = new Map()
const out = []
let dropped = 0, droppedChars = 0
for (const b of blocks) {
  const key = b.head
  const body = norm(b.body.join(NL))
  if (key && seen.has(key) && seen.get(key) === body) {
    dropped++
    droppedChars += b.head.length + b.body.join(NL).length
    continue // 同名同内容：整块丢弃（标题也只留一次）
  }
  if (key) seen.set(key, body)
  out.push(b.head ? [b.head, ...b.body].join(NL) : b.body.join(NL))
}

const deduped = out.join(NL)
console.log('blocks:', blocks.length, 'dropped:', dropped)
console.log('chars:', sys.length, '->', deduped.length, '(节省', (sys.length - deduped.length), '≈', Math.round((sys.length - deduped.length) / 3.93), 'tokens)')
fs.writeFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/system-dedup.txt', deduped)

// 展示被丢弃的标题
const seen2 = new Map()
for (const b of blocks) {
  const k = b.head
  if (!k) continue
  const body = norm(b.body.join(NL))
  seen2.set(k, (seen2.get(k) || 0) + 1)
}
const rep = [...seen2.entries()].filter(([, c]) => c > 1)
console.log('重复标题:', rep.map(([t, c]) => c + 'x ' + t).join(' | '))
