// 单独把 registerAdapter: true 插到 desktop profile 的 dsh-ninfer-local 条目里
import fs from 'node:fs'

const F = 'C:/Users/Administrator/.dsh/profiles/desktop/cordis.yml'
const raw = fs.readFileSync(F, 'utf8')
if (raw.includes('registerAdapter')) {
  console.log('already present, nothing to do')
  process.exit(0)
}
const lines = raw.split('\n')
const idIdx = lines.findIndex((l) => l.trim() === '- id: dsh-ninfer-local')
if (idIdx < 0) { console.log('entry not found'); process.exit(1) }
let cfgIdx = -1
for (let k = idIdx + 1; k < idIdx + 8; k++) {
  if (lines[k] === '  config:') { cfgIdx = k; break }
}
if (cfgIdx < 0) { console.log('config: line not found near entry'); process.exit(1) }
lines.splice(cfgIdx + 1, 0, '    registerAdapter: true')
fs.writeFileSync(F, lines.join('\n'))
console.log('inserted at line', cfgIdx + 2, '(id at', idIdx + 1, ')')
