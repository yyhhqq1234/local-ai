// 2026-11-18 从 profile pnpm-lock.yaml 的 importers 段删掉 @dsh-external/dsh-ninfer-local 块
// 规则：命中行起，删除该行与其后所有「缩进更深」的行，遇到缩进 <= 命中行缩进 的下一行即停。
// 校验：删除后再次 grep 该 key 必须为 0；否则不写。
// 用法: node rm-ninfer-lock.mjs "<pnpm-lock.yaml 绝对路径>"
import fs from 'node:fs'

const p = process.argv[2]
if (!p) { console.error('missing path'); process.exit(2) }

const KEY = "'@dsh-external/dsh-ninfer-local'"
const raw = fs.readFileSync(p, 'utf8')
const eol = raw.includes('\r\n') ? '\r\n' : '\n'
const lines = raw.split(/\r?\n/)

const indentOf = (s) => s.length - s.replace(/^\s+/, '').length

const out = []
let removed = 0
let skipDeeperThan = -1
for (const l of lines) {
  const ind = indentOf(l)
  if (skipDeeperThan >= 0) {
    if (l.trim() === '' || ind > skipDeeperThan) { continue }
    skipDeeperThan = -1
  }
  if (l.includes(KEY)) {
    skipDeeperThan = ind
    removed++
    continue
  }
  out.push(l)
}

if (removed === 0) { console.log(JSON.stringify({ changed: false, note: 'key not present' })); process.exit(0) }

const next = out.join(eol)
if (next.includes(KEY)) { console.error('ABORT: key still present after filter'); process.exit(3) }

const bak = p + '.bak-rmninfer-' + Date.now()
fs.copyFileSync(p, bak)
fs.writeFileSync(p, next)
console.log(JSON.stringify({ changed: true, removedBlocks: removed, backup: bak, linesBefore: lines.length, linesAfter: out.length }, null, 2))
