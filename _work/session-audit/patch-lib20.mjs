// 思考档从"硬覆盖 minimal"改为"上限封顶"：尊重用户选择，只把 high/xhigh/max 压到上限
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to); done.push(name)
}

// 1) 配置：forceReasoningEffort → effortCap
rep('cfg-cap',
  "  forceReasoningEffort: 'minimal',",
  "  effortCap: 'medium',   // 思考档上限：用户选 ≤medium 时尊重；high/xhigh/max 一律压到 medium（防 8K 预算被思考吃光）")

// 2) 传参
rep('ctor-cap',
  '      forceReasoningEffort: cfg.forceReasoningEffort,',
  '      effortCap: cfg.effortCap,')

// 3) 应用逻辑
rep('apply-cap',
  '    if (this.profile.forceReasoningEffort) body.reasoning_effort = String(this.profile.forceReasoningEffort)' + NL +
  '    else if (options.reasoningEffort) body.reasoning_effort = String(options.reasoningEffort)',
  '    {' + NL +
  "      const ORDER = ['none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max']" + NL +
  '      const want = String(options.reasoningEffort || this.profile.defaultEffort || "minimal")' + NL +
  '      const cap = this.profile.effortCap ? String(this.profile.effortCap) : ""' + NL +
  '      let eff = want' + NL +
  '      if (cap) {' + NL +
  '        const wi = ORDER.indexOf(want)' + NL +
  '        const ci = ORDER.indexOf(cap)' + NL +
  '        if (ci >= 0 && (wi < 0 || wi > ci)) eff = cap' + NL +
  '      }' + NL +
  '      body.reasoning_effort = eff' + NL +
  '    }')

fs.writeFileSync(P + '.bak-think20', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
