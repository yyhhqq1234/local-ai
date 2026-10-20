// 修复 "Assistant stream chunk must be losslessly JSON-serializable"
// 原因：usage 里 reasoningTokens/cacheReadTokens 用了 `|| undefined`，undefined 字段不可无损序列化
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

const FROM = [
  '    if (usage) {',
  "      yield {",
  "        type: 'usage',",
  '        usage: {',
  '          inputTokens: Number(usage.prompt_tokens ?? 0),',
  '          outputTokens: Number(usage.completion_tokens ?? 0),',
  '          totalTokens: Number(usage.total_tokens ?? 0),',
  '          reasoningTokens: Number(usage.completion_tokens_details?.reasoning_tokens ?? 0) || undefined,',
  '          cacheReadTokens: Number(usage.prompt_tokens_details?.cached_tokens ?? 0) || undefined,',
  '        },',
  '      }',
  '    }',
].join(NL)

const TO = [
  '    if (usage) {',
  "      // 只放有值的数字字段：undefined 会让 DSH 判 ",
  "      // \"Assistant stream chunk must be losslessly JSON-serializable\"",
  '      const u = {',
  '        inputTokens: Number(usage.prompt_tokens ?? 0),',
  '        outputTokens: Number(usage.completion_tokens ?? 0),',
  '        totalTokens: Number(usage.total_tokens ?? 0),',
  '      }',
  '      const rt = Number(usage.completion_tokens_details?.reasoning_tokens ?? 0)',
  '      if (rt > 0) u.reasoningTokens = rt',
  '      const cr = Number(usage.prompt_tokens_details?.cached_tokens ?? 0)',
  '      if (cr > 0) u.cacheReadTokens = cr',
  "      yield { type: 'usage', usage: u }",
  '    }',
].join(NL)

rep('usage-no-undefined', FROM, TO)

fs.writeFileSync(P + '.bak-think5', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
