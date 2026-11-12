// p3_realshape_probe.mjs — ③ 真实形态压测：35K 字符 system + 14 工具 + 16K 预算裁剪路径
// 目的：确认「协议注入」在 system 被 compressSystem 截断后仍然存活，且真实会话不 500 / 不乱码。
import { NinferAdapter } from '../../plugins/dsh-ninfer-local/lib/index.js'

const MODEL = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'

// 模拟 DSH 的 system：约定段（重复度高）+ 技能目录块 + 工具提示
const RULES = Array.from({ length: 40 }, (_, i) =>
  '## 约定段 ' + (i + 1) + '\n本段是工作区运行约定，用于说明交付形态与推进规则。' +
  '结论优先，参数缺失按占位符推进；路径不可用时记录原因并改等价路径。').join('\n\n')
const SKILLS = '<available_skills>\n' + Array.from({ length: 120 }, (_, i) =>
  '- `skill-' + i + '`: 这是第 ' + i + ' 个技能的说明行，用于占位与体积模拟。').join('\n') + '\n</available_skills>'
const TOOL_HINT = Array.from({ length: 30 }, (_, i) =>
  '工具说明 ' + i + '：按 schema 给全参数，先看回包再决定下一步。').join('\n')
const SYSTEM = [RULES, SKILLS, TOOL_HINT].join('\n\n')

const TOOLS = [
  ['read', { path: { type: 'string' }, limit: { type: 'number' } }, ['path']],
  ['write', { file_path: { type: 'string' }, content: { type: 'string' } }, ['file_path', 'content']],
  ['edit', { file_path: { type: 'string' }, old_string: { type: 'string' }, new_string: { type: 'string' } }, ['file_path', 'old_string', 'new_string']],
  ['ops_bash', { command: { type: 'string' }, description: { type: 'string' } }, ['command', 'description']],
  ['ops_glob', { pattern: { type: 'string' } }, ['pattern']],
  ['ops_grep', { pattern: { type: 'string' }, path: { type: 'string' } }, ['pattern']],
  ['skill', { name: { type: 'string' } }, ['name']],
  ['web_search', { queries: { type: 'array', items: { type: 'string' } } }, ['queries']],
  ['ninfer_status', { action: { type: 'string' } }, []],
  ['ninfer_engine', { action: { type: 'string' }, profile: { type: 'string' } }, ['action']],
  ['kitty_ce', { op: { type: 'string' } }, []],
  ['kitty_ops', { filter: { type: 'string' } }, []],
  ['kitty_settings', { action: { type: 'string' } }, ['action']],
  ['kitty_status', { probe: { type: 'boolean' } }, []],
].map(([name, props, req]) => ({
  name, description: name + ' 工具', parameters: { type: 'object', properties: props, required: req },
}))

const profile = {
  baseURL: 'http://127.0.0.1:1234/v1',
  displayName: 'realshape',
  timeoutMs: 8000,
  toolAllowlist: TOOLS.map((t) => t.name),
  slimSkills: true, slimSystem: true, stripToolHints: [],
  emitReasoning: true,
  executionRules: '',
  sampling: { enabled: false },
  detectRepeatToolCalls: false,
  stuckBreaker: false,
  errorHints: false,
  offloadToolResultMaxChars: 0,
  skillNameLimit: 60,
  defaultEffort: 'none',
  effortCap: 'none',
  // 与真实档位一致（ENGINE_PROFILES.build-9b.contextBudget）
  contextBudget: { window: 16384, maxOutput: 1024, reserve: 256 },
  profileFlags: () => ({
    textToolCalls: true,
    compactSystem: true,
    compactSystemText: '你是石井，本地工作区执行层。中文、简短、直接；先给结论后给理由。',
    compactHistoryMessages: 6,
  }),
}

const adapter = new NinferAdapter(profile)
const T = (s) => [{ type: 'text', text: s }]

async function run(name, user, maxTokens, expectTool) {
  const t0 = Date.now()
  let firstText = null
  const ends = []
  let finish = null
  let usage = null
  for await (const c of adapter.stream({
    model: MODEL,
    system: SYSTEM,
    messages: [{ role: 'user', content: T(user) }],
    tools: TOOLS, maxTokens, temperature: 0, reasoningEffort: 'none',
  })) {
    if (c.type === 'block-end') ends.push(c)
    if (c.type === 'finish') finish = c.reason
    if (c.type === 'usage') usage = c.usage
    if (c.type === 'text-delta' && firstText === null) firstText = Date.now() - t0
  }
  const text = ends.find((c) => c.block?.type === 'text')?.block?.text ?? ''
  const calls = ends.filter((c) => c.block?.type === 'tool-call').map((c) => {
    let args = null
    try { args = JSON.parse(c.block.arguments) } catch { args = c.block.arguments }
    return { name: c.block.name, args }
  })
  const bad = /\ufffd/.test(text) || /(.)\1{6,}/.test(text)
  const ok = calls.length > 0 === expectTool && !bad && text.length + calls.length > 0
  console.log('\n=== ' + name + ' === ' + (ok ? 'PASS' : 'FAIL'))
  console.log('  systemChars=' + SYSTEM.length + ' tools=' + TOOLS.length + ' maxTokens=' + maxTokens)
  console.log('  wall=' + (Date.now() - t0) + 'ms firstTextDelta=' + firstText + 'ms finish=' + JSON.stringify(finish))
  console.log('  usage=' + JSON.stringify(usage) + ' garbled=' + bad)
  console.log('  text=' + JSON.stringify(text.slice(0, 160)))
  console.log('  calls=' + JSON.stringify(calls).slice(0, 400))
  return ok
}

const a = await run('R1 真实形态·普通问答', '用一句话说明本地推理最大的好处。', 96, false)
const b = await run('R2 真实形态·工具任务', '读取 README.md 前 20 行。', 160, true)
console.log('\nRESULT ' + [a, b].filter(Boolean).length + '/2 pass')
process.exit(a && b ? 0 : 1)
