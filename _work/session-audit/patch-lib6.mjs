// 修复漏裁：skills 清单注入在 user 消息（<system-reminder>），之前只处理了 role==='system'
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

rep('slim-all-messages',
  [
    "    if (this.profile.slimSkills !== false) {",
    '      for (const m of messages) {',
    "        if (m.role === 'system' && typeof m.content === 'string') {",
    '          m.content = slimSkillsBlock(m.content, this.profile.skillNameLimit)',
    '          if (this.profile.slimSystem !== false) m.content = dedupeSystem(m.content)',
    '        }',
    '      }',
    '    }',
  ].join(NL),
  [
    '    // 技能清单可能注入在 system 或 user(<system-reminder>) 消息里 —— 两种都要折叠',
    '    if (this.profile.slimSkills !== false) {',
    '      for (const m of messages) {',
    "        if (typeof m.content !== 'string' || !m.content) continue",
    "        if (m.content.indexOf('<available_skills>') >= 0) {",
    '          m.content = slimSkillsBlock(m.content, this.profile.skillNameLimit)',
    '        }',
    '        // 段去重只对 system 做，避免动用户正文',
    "        if (m.role === 'system' && this.profile.slimSystem !== false) {",
    '          m.content = dedupeSystem(m.content)',
    '        }',
    '      }',
    '    }',
  ].join(NL))

// 统计口径也要覆盖全部消息里的 system-reminder 体积，便于验证
rep('stats-all-chars',
  "        const systemChars = messages.reduce((a, m) => a + (m.role === 'system' && typeof m.content === 'string' ? m.content.length : 0), 0)",
  "        const systemChars = messages.reduce((a, m) => a + (m.role === 'system' && typeof m.content === 'string' ? m.content.length : 0), 0)" + NL +
  "        const totalChars = messages.reduce((a, m) => a + (typeof m.content === 'string' ? m.content.length : 0), 0)")

rep('stats-include-total',
  "appendFileSync(this.profile.statsPath, JSON.stringify({ ts: Date.now(), model: options.model, tools: tools?.length ?? 0, systemChars, payloadBytes: JSON.stringify(body).length }) + String.fromCharCode(10))",
  "appendFileSync(this.profile.statsPath, JSON.stringify({ ts: Date.now(), model: options.model, tools: tools?.length ?? 0, systemChars, totalChars, payloadBytes: JSON.stringify(body).length }) + String.fromCharCode(10))")

fs.writeFileSync(P + '.bak-think6', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
