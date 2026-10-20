// 修复「回复被吞」：block-end 必须携带累积正文，DSH 以 block-end.block 作为最终内容
// 同时补 stream_options.include_usage，让 usage 回传
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

// 1) 累积缓冲
rep('buffers',
  '    let textStarted = false, reasoningStarted = false',
  '    let textStarted = false, reasoningStarted = false' + NL +
  '    let textBuf = \'\', reasonBuf = \'\'')

// 2) reasoning 累加
rep('reason-accum',
  "        yield { type: 'reasoning-delta', index: reasoningIndex, text: think }",
  '        reasonBuf += think' + NL +
  "        yield { type: 'reasoning-delta', index: reasoningIndex, text: think }")

// 3) text 累加
rep('text-accum',
  "        yield { type: 'text-delta', index: textIndex, text: delta.content }",
  '        textBuf += delta.content' + NL +
  "        yield { type: 'text-delta', index: textIndex, text: delta.content }")

// 4) 切换到 text 时，reasoning 的 block-end 带上累积内容（10 空格缩进）
rep('reason-end-inline',
  "          yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: '' } }",
  "          yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: reasonBuf } }")

// 5) 结尾 reasoning 的 block-end（6 空格缩进）
rep('reason-end-final',
  "      yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: '' } }",
  "      yield { type: 'block-end', index: reasoningIndex, block: { type: 'reasoning', text: reasonBuf } }")

// 6) 结尾 text 的 block-end 带正文
rep('text-end-final',
  "      yield { type: 'block-end', index: textIndex, block: { type: 'text', text: '' } }",
  "      yield { type: 'block-end', index: textIndex, block: { type: 'text', text: textBuf } }")

// 7) 让引擎回 usage
rep('stream-options',
  '      stream: true,' + NL + '      temperature: options.temperature,',
  '      stream: true,' + NL + '      stream_options: { include_usage: true },' + NL + '      temperature: options.temperature,')

fs.writeFileSync(P + '.bak-think4', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
