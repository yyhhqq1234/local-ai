// 修复 "tool-call-delta index must be a non-negative safe integer"
// 原因：lib 的 tool-call-delta 没带 index；DSH 要求非负安全整数，且 name 不能是 undefined
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []

function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to)
  done.push(name)
}

// 1) 工具索引表
rep('tool-index-map',
  '    const toolCalls = new Map()',
  '    const toolCalls = new Map()' + NL +
  '    const toolIndexById = new Map()')

// 2) tool-call-delta 带 index，name 只在有值时给
rep('tool-call-delta',
  "          yield { type: 'tool-call-delta', id, name: cur.name || undefined, argumentsDelta: tc.function?.arguments ?? '' }",
  '          let tIdx = toolIndexById.get(id)' + NL +
  '          if (tIdx === undefined) { tIdx = toolIndexById.size; toolIndexById.set(id, tIdx) }' + NL +
  "          const deltaChunk = { type: 'tool-call-delta', index: tIdx, id, argumentsDelta: tc.function?.arguments ?? '' }" + NL +
  '          if (cur.name) deltaChunk.name = cur.name' + NL +
  '          yield deltaChunk')

// 3) tool-call 的 block-end 也用同一 index（不再硬编码 0，避免与 text 块冲突）
rep('tool-block-end',
  "    for (const [id, c] of toolCalls) {" + NL +
  "      yield { type: 'block-end', index: 0, block: { type: 'tool-call', id, name: c.name, arguments: c.args } }" + NL +
  '    }',
  '    for (const [id, c] of toolCalls) {' + NL +
  '      const tIdx = toolIndexById.get(id) ?? 0' + NL +
  '      yield { type: \'block-end\', index: (textStarted ? 1 : 0) + tIdx, block: { type: \'tool-call\', id, name: c.name, arguments: c.args } }' + NL +
  '    }')

fs.writeFileSync(P + '.bak-think7', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
