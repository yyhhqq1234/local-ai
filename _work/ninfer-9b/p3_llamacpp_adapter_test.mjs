// p3_llamacpp_adapter_test.mjs — 验证新增的 llama-cpp 档：适配器把请求转发到 Ollama，
// 并把原生 tool_calls 透传给 DSH（不需要文本 shim）
import { NinferAdapter } from '../../plugins/dsh-ninfer-local/lib/index.js'

const BASE = 'http://127.0.0.1:8080/v1'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/_work/infer-9b/gguf/kittyrev9b-Q5_K_M-im.gguf'

const profile = {
  baseURL: 'http://127.0.0.1:1234/v1',      // 模拟默认配置（非外部档）
  profileBaseUrl: () => BASE,                // 新加的动态端点：外部档生效
  displayName: 'llama-cpp-test',
  timeoutMs: 8000,
  toolAllowlist: ['read', 'ops_bash'],
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
  profileFlags: () => ({ textToolCalls: false, compactSystem: false }),
}

const TOOLS = [
  { name: 'read', description: '读取文本文件', parameters: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] } },
]

const adapter = new NinferAdapter(profile)
const T = (s) => [{ type: 'text', text: s }]
const chunks = []
let firstText = null
const t0 = Date.now()
for await (const c of adapter.stream({
  model: MODEL,
  messages: [{ role: 'user', content: T('读取 README.md 前 5 行') }],
  tools: TOOLS, maxTokens: 128, temperature: 0, reasoningEffort: 'none',
})) {
  chunks.push(c)
  if (c.type === 'text-delta' && firstText === null) firstText = Date.now() - t0
}
const ends = chunks.filter((c) => c.type === 'block-end')
const calls = ends.filter((c) => c.block?.type === 'tool-call').map((c) => ({ name: c.block.name, args: c.block.arguments }))
const finish = chunks.find((c) => c.type === 'finish')
console.log(JSON.stringify({
  tool_calls: calls,
  finish: finish?.reason,
  first_text_ms: firstText,
  wall_ms: Date.now() - t0,
  ok: calls.length > 0 && calls[0].name === 'read',
}, null, 1))
process.exit(calls.length ? 0 : 1)

