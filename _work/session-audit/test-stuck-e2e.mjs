// 空转熔断端到端回归：真 adapter.stream + 本地 SSE 桩（不碰 1234 引擎）
// 跑法：node D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\test-stuck-e2e.mjs
import http from 'node:http'
import { NinferAdapter } from '../../plugins/dsh-ninfer-local/lib/index.js'

const PORT = 18934
const srv = http.createServer((req, res) => {
  if (req.url.endsWith('/models')) {
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ data: [{ id: 'stub-model', context_window: 262144 }] }))
    return
  }
  if (req.url.endsWith('/chat/completions')) {
    let body = ''
    req.on('data', (c) => { body += c })
    req.on('end', () => {
      res.writeHead(200, { 'content-type': 'text/event-stream' })
      const push = (o) => res.write('data: ' + JSON.stringify(o) + '\n\n')
      push({ choices: [{ delta: { content: '收到' } }] })
      push({ choices: [{ delta: {}, finish_reason: 'stop' }], usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } })
      res.write('data: [DONE]\n\n')
      res.end()
    })
    return
  }
  res.writeHead(404); res.end('no')
})

const call = (name, args) => ({ role: 'assistant', content: [{ type: 'tool-call', id: 'c' + Math.random(), name, arguments: JSON.stringify(args) }] })
const tool = (text) => ({ role: 'tool', content: [{ type: 'text', text }] })
const seq = (arr) => arr.flatMap(([n, a, r]) => [call(n, a), tool(r)])

function profile() {
  return {
    baseURL: `http://127.0.0.1:${PORT}/v1`,
    displayName: 'stub',
    fallbackModels: [{ id: 'stub-model', name: 'stub', contextWindow: 262144, maxTokens: 8192 }],
    emitReasoning: true,
    timeoutMs: 5000,
    toolAllowlist: null,
    slimSkills: false,
    slimSystem: false,
    stripToolHints: [],
    executionRules: '',
    sampling: { enabled: false },
    detectRepeatToolCalls: false,
    stuckBreaker: true,
    errorHints: false,
    offloadToolResultMaxChars: 0,
    skillNameLimit: 0,
    defaultEffort: 'minimal',
    effortCap: '',
    statsPath: undefined,
  }
}

async function run(name, messages) {
  const ad = new NinferAdapter(profile())
  const chunks = []
  for await (const c of ad.stream({ model: 'stub-model', messages, temperature: 0.2, maxTokens: 512, tools: [], reasoningEffort: 'minimal' })) chunks.push(c)
  const fin = chunks.filter((c) => c.type === 'finish').pop()
  const text = chunks.filter((c) => c.type === 'text-delta').map((c) => c.text).join('')
  return { name, finish: fin?.reason?.kind ?? '-', code: fin?.reason?.failure?.code ?? '', text: text.slice(0, 60) }
}

await new Promise((r) => srv.listen(PORT, '127.0.0.1', r))
const results = []
try {
  // 1) 旧版必误杀：同工具 6 次、参数键相同但值不同
  results.push(await run('normal-long-task', seq([
    ...Array.from({ length: 6 }, (_, i) => ['read', { file_path: `F:/w/f${i}.md`, limit: 200 }, `# f${i}`]),
    ...Array.from({ length: 6 }, (_, i) => ['ops_bash', { command: `echo ${i}`, description: `s${i}` }, `out${i}`]),
  ])))
  // 2) 真卡死：同一工具同一参数连续 6 次
  results.push(await run('true-stuck', seq(Array.from({ length: 6 }, () => ['kitty_settings', { action: 'task-close' }, 'ERR|EARLY-EXIT-DENY']))))
} finally {
  srv.close()
}

console.table(results)
const a = results[0], b = results[1]
const ok = a.code !== 'STUCK_LOOP' && a.finish === 'stop' && a.text.includes('收到') && b.code === 'STUCK_LOOP' && b.finish === 'error'
console.log(ok ? '\nPASS：正常长任务放行（finish=stop），真卡死仍熔断（STUCK_LOOP）' : '\nFAIL：行为与预期不符')
process.exit(ok ? 0 : 1)
