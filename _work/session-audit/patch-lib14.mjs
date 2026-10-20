// 采样分流（按任务类型选 temperature/top_p/presence_penalty）+ 撤销 kitty 剥离
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

// 1) 撤销 kitty 剥离（用户要求保留 kitty 上下文）
rep('drop-kitty',
  "  stripToolHints: ['kitty', 'js-reverse', 'jobs'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）",
  "  stripToolHints: ['js-reverse', 'jobs'],   // 白名单里没有的工具，其使用说明一并剔除（kitty 按操作者要求保留）")

// 2) 采样档配置
rep('cfg-sampling',
  '  offloadToolResultMaxChars: 2000,',
  '  sampling: {' + NL +
  '    enabled: true,' + NL +
  '    code: { temperature: 0.2, topP: 0.95, presencePenalty: 0 },' + NL +
  '    creative: { temperature: 0.8, topP: 0.92, presencePenalty: 0.3 },' + NL +
  '    fact: { temperature: 0.1, topP: 0.9, presencePenalty: 0 },' + NL +
  '    default: { temperature: 0.6, topP: 0.95, presencePenalty: 0 },' + NL +
  '  },' + NL +
  '  offloadToolResultMaxChars: 2000,')

// 3) 传参
rep('ctor-sampling',
  '      offloadToolResultMaxChars: cfg.offloadToolResultMaxChars,',
  '      sampling: cfg.sampling,' + NL + '      offloadToolResultMaxChars: cfg.offloadToolResultMaxChars,')

// 4) 应用采样（body 构造处）
rep('apply-sampling',
  '      stream: true,' + NL + '      stream_options: { include_usage: true },' + NL + '      temperature: options.temperature,',
  '      stream: true,' + NL + '      stream_options: { include_usage: true },' + NL + '      temperature: options.temperature,')

// 实际覆盖放在 body 之后：找到 stats 写入前的锚点
rep('override-sampling',
  '    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))',
  '    let sampleKind = ""' + NL +
  '    if (this.profile.sampling && this.profile.sampling.enabled !== false) {' + NL +
  '      const picked = pickSampling(messages, this.profile.sampling)' + NL +
  '      sampleKind = picked.kind' + NL +
  '      body.temperature = picked.temperature' + NL +
  '      body.top_p = picked.topP' + NL +
  '      if (picked.presencePenalty > 0) body.presence_penalty = picked.presencePenalty' + NL +
  '    }' + NL +
  '    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))')

// 5) stats 里带 sampleKind
rep('stats-sample',
  "appendFileSync(this.profile.statsPath, JSON.stringify({ ts: Date.now(), model: options.model, tools: tools?.length ?? 0, systemChars, totalChars, payloadBytes: JSON.stringify(body).length }) + String.fromCharCode(10))",
  "appendFileSync(this.profile.statsPath, JSON.stringify({ ts: Date.now(), model: options.model, tools: tools?.length ?? 0, systemChars, totalChars, sample: sampleKind, payloadBytes: JSON.stringify(body).length }) + String.fromCharCode(10))")

// 6) pickSampling 实现
const impl = [
  'function pickSampling(messages, cfg) {',
  '  let text = ""',
  '  for (let i = messages.length - 1; i >= 0; i--) {',
  "    if (messages[i].role !== 'user') continue",
  '    const c = messages[i].content',
  "    const txt = typeof c === 'string' ? c : (Array.isArray(c) ? c.map((b) => (b && b.text) || '').join(' ') : '')",
  '    if (txt) { text = txt; break }',
  '  }',
  '  const t = text || ""',
  '  const codeRe = /(代码|脚本|函数|实现|命令|接口|class |def |import |html|css|svg|json|yaml|sql|正则|编译|部署|配置)/i',
  '  const creativeRe = /(写|创作|小说|文案|诗|故事|剧本|旁白|散文|角色|对话)/',
  '  const factRe = /(解释|什么是|为什么|区别|原理|计算|多少|定义|对比|评估)/',
  '  let kind = "default"',
  '  if (codeRe.test(t)) kind = "code"',
  '  else if (creativeRe.test(t) && !codeRe.test(t)) kind = "creative"',
  '  else if (factRe.test(t)) kind = "fact"',
  '  const p = cfg[kind] || cfg.default || {}',
  '  return {',
  '    kind,',
  '    temperature: typeof p.temperature === "number" ? p.temperature : 0.6,',
  '    topP: typeof p.topP === "number" ? p.topP : 0.95,',
  '    presencePenalty: typeof p.presencePenalty === "number" ? p.presencePenalty : 0,',
  '  }',
  '}',
].join(NL)

rep('impl-sampling', 'function toOpenAITools(tools) {', impl + NL + NL + 'function toOpenAITools(tools) {')

fs.writeFileSync(P + '.bak-think14', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
