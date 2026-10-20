// A 方案：把 provider ninfer 从 llm-pi-ai 迁到 dsh-ninfer-local 的 NinferAdapter
// 只删 llm-pi-ai.providers.ninfer 一段 + 给 dsh-ninfer-local 加 registerAdapter: true
import fs from 'node:fs'

const DRY = process.argv.includes('--dry')
const FILES = [
  'C:/Users/Administrator/.dsh/profiles/desktop/cordis.patch.yml',
  'C:/Users/Administrator/.dsh/profiles/desktop/cordis.yml',
]

function dropNinferProvider(text, label) {
  const lines = text.split('\n')
  const start = lines.findIndex((l) => /^\s{6}ninfer:\s*$/.test(l))
  if (start < 0) return { text, info: label + ': ninfer provider not found (skip)' }
  // 结束：下一个缩进 <= 6 的非空、非注释行
  let end = start + 1
  while (end < lines.length) {
    const l = lines[end]
    if (l.trim() === '' || l.trim().startsWith('#')) { end++; continue }
    const indent = l.match(/^ */)[0].length
    if (indent <= 6) break
    end++
  }
  const dropped = lines.slice(start, end)
  const out = [...lines.slice(0, start), ...lines.slice(end)].join('\n')
  return { text: out, info: `${label}: drop lines ${start + 1}-${end} (${dropped.length} lines)` }
}

function addRegisterAdapter(text, label) {
  const lines = text.split('\n')
  const i = lines.findIndex((l) => /^- id: dsh-ninfer-local\s*$/.test(l))
  if (i < 0) return { text, info: label + ': dsh-ninfer-local entry not found (skip)' }
  if (lines.slice(i, i + 8).some((l) => /registerAdapter:/.test(l))) {
    return { text, info: label + ': registerAdapter already present' }
  }
  // 插到该条目的 config: 之后（保持 4 空格缩进）
  let cfgIdx = -1
  for (let k = i + 1; k < Math.min(i + 10, lines.length); k++) {
    if (/^\s{2}config:\s*$/.test(lines[k])) { cfgIdx = k; break }
  }
  if (cfgIdx < 0) return { text, info: label + ': config: not found under entry (skip)' }
  lines.splice(cfgIdx + 1, 0, '    registerAdapter: true')
  return { text: lines.join('\n'), info: `${label}: add registerAdapter: true after line ${cfgIdx + 1}` }
}

for (const f of FILES) {
  const raw = fs.readFileSync(f, 'utf8')
  let r1 = dropNinferProvider(raw, f)
  let r2 = addRegisterAdapter(r1.text, f)
  console.log(r1.info)
  console.log(r2.info)
  if (r2.text === raw) { console.log('  -> unchanged'); continue }
  if (DRY) { console.log('  -> DRY, not written'); continue }
  fs.writeFileSync(f + '.bak-armor', raw)
  fs.writeFileSync(f, r2.text)
  console.log('  -> written, backup:', f + '.bak-armor')
}
