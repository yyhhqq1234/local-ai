// 2026-11-18 从 desktop profile 的 dependencies 摘掉 @dsh-external/dsh-ninfer-local
// 只做文本行删除（保留原缩进），写回前 JSON.parse 校验；失败不写。
// 用法: node rm-ninfer-dep.mjs "<profile package.json 绝对路径>"
import fs from 'node:fs'

const p = process.argv[2]
if (!p) { console.error('missing path'); process.exit(2) }

const KEY = '@dsh-external/dsh-ninfer-local'
const raw = fs.readFileSync(p, 'utf8')
const lines = raw.split(/\r?\n/)

const hit = []
const out = []
for (let i = 0; i < lines.length; i++) {
  const l = lines[i]
  if (l.includes(`"${KEY}"`)) { hit.push({ line: i + 1, text: l.trim() }); continue }
  out.push(l)
}

if (hit.length === 0) { console.log(JSON.stringify({ changed: false, note: 'key not present' })); process.exit(0) }

const next = out.join('\n')
let parsed
try { parsed = JSON.parse(next) } catch (e) {
  console.error('ABORT: result is not valid JSON -> ' + e.message)
  process.exit(3)
}
if (parsed.dependencies && Object.prototype.hasOwnProperty.call(parsed.dependencies, KEY)) {
  console.error('ABORT: key still present after filter')
  process.exit(4)
}

const bak = p + '.bak-rmninfer-' + Date.now()
fs.copyFileSync(p, bak)
fs.writeFileSync(p, next)
console.log(JSON.stringify({ changed: true, removedLines: hit, backup: bak, deps: Object.keys(parsed.dependencies || {}).length }, null, 2))
