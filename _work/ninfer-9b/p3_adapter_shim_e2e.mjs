// p3_adapter_shim_e2e.mjs — 走适配器真实 stream() 链路验证「文本→tool_call」shim
// 前提：9B 引擎已在 127.0.0.1:1234 运行（ninfer_engine start profile=build-9b）
import { NinferAdapter } from '../../plugins/dsh-ninfer-local/lib/index.js'

const MODEL = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
const TOOLS = [
  { name: 'read', description: '读取文本文件的指定行区间',
    parameters: { type: 'object', properties: { path: { type: 'string' }, limit: { type: 'number' } }, required: ['path'] } },
  { name: 'ops_bash', description: '执行一条 bash 命令',
    parameters: { type: 'object', properties: { command: { type: 'string' }, description: { type: 'string' } }, required: ['command', 'description'] } },
  { name: 'kitty_ce', description: 'KittyCE 通道执行内存指令',
    parameters: { type: 'object', properties: { op: { type: 'string' } }, required: ['op'] } },
]

const profile = {
  baseURL: 'http://127.0.0.1:1234/v1',
  displayName: 'adapter-shim-test',
  timeoutMs: 8000,
  toolAllowlist: TOOLS.map((t) => t.name),
  slimSkills: false, slimSystem: false, stripToolHints: [],
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
  profileFlags: () => ({ textToolCalls: true }),
}

const adapter = new NinferAdapter(profile)

async function run(name, messages, maxTokens, expectTool) {
  const chunks = []
  const t0 = Date.now()
  let firstText = null
  for await (const c of adapter.stream({
    model: MODEL, messages, tools: TOOLS, maxTokens, temperature: 0, reasoningEffort: 'none',
  })) {
    chunks.push(c)
    if (c.type === 'text-delta' && firstText === null) firstText = Date.now() - t0
  }
  const ends = chunks.filter((c) => c.type === 'block-end')
  const textEnd = ends.find((c) => c.block?.type === 'text')
  const toolEnds = ends.filter((c) => c.block?.type === 'tool-call')
  const finish = chunks.find((c) => c.type === 'finish')
  const deltas = chunks.filter((c) => c.type === 'tool-call-delta')
  const text = textEnd?.block?.text ?? ''
  const calls = toolEnds.map((c) => {
    let args = null
    try { args = JSON.parse(c.block.arguments) } catch { args = c.block.arguments }
    return { id: c.block.id, name: c.block.name, args }
  })
  let ok = true
  const why = []
  if (expectTool) {
    if (!calls.length) { ok = false; why.push('没有解析出 tool-call') }
    else if (!TOOLS.some((t) => t.name === calls[0].name)) { ok = false; why.push('工具名不在白名单: ' + calls[0].name) }
    else if (typeof calls[0].args !== 'object' || !calls[0].args) { ok = false; why.push('arguments 不是对象') }
    if (!deltas.length) { ok = false; why.push('缺 tool-call-delta') }
    if (finish?.reason?.kind !== 'tool-calls') { ok = false; why.push('finish=' + finish?.reason?.kind) }
    if (/<tool_call>|kitty_ce op=/.test(text)) { ok = false; why.push('正文残留标记') }
  } else {
    if (calls.length) { ok = false; why.push('普通问答误判成工具调用') }
    if (!text.trim()) { ok = false; why.push('正文为空') }
    if (finish?.reason?.kind !== 'stop' && finish?.reason?.kind !== 'max-tokens') { ok = false; why.push('finish=' + finish?.reason?.kind) }
  }
  console.log('\n=== ' + name + ' === ' + (ok ? 'PASS' : 'FAIL') + (why.length ? ' | ' + why.join('; ') : ''))
  console.log('  wall=' + (Date.now() - t0) + 'ms firstTextDelta=' + firstText + 'ms')
  console.log('  finish=' + JSON.stringify(finish?.reason ?? null))
  console.log('  text=' + JSON.stringify(text.slice(0, 220)))
  console.log('  calls=' + JSON.stringify(calls))
  console.log('  usage=' + JSON.stringify(chunks.find((c) => c.type === 'usage')?.usage ?? null))
  return ok
}

const T = (s) => [{ type: 'text', text: s }]

const r1 = await run('T1 工具任务（应产出 read 调用）', [
  { role: 'system', content: T('你是石井，本地工作区执行层。需要读文件时必须调用 read 工具，不要凭记忆编造文件内容。') },
  { role: 'user', content: T('读取 README.md 的前 20 行，然后告诉我第一行是什么。') },
], 160, true)

const r2 = await run('T2 普通问答（不得误判）', [
  { role: 'system', content: T('你是石井，本地工作区执行层。中文、简短、直接。') },
  { role: 'user', content: T('用一句话说明本地推理最大的好处。') },
], 80, false)

const r3 = await run('T3 kitty 任务（应产出 kitty_ce 调用）', [
  { role: 'system', content: T('你是 kitty 逆向工作台的执行层，直接调用 kitty_* 工具完成逆向任务。') },
  { role: 'user', content: T('目标进程 kitty-target.exe 已 OPEN，读一下模块基址处的 dword。') },
], 160, true)

console.log('\nRESULT ' + [r1, r2, r3].filter(Boolean).length + '/3 pass')
process.exit(r1 && r2 && r3 ? 0 : 1)
