// 验证插件适配器在"当前跑哪个引擎"下的模型列表与 8080 端点行为
import { NinferAdapter } from '../../plugins/dsh-local-ai/lib/index.js'

const adapter = new NinferAdapter({
  baseURL: 'http://127.0.0.1:8080/v1',
  displayName: 'NInfer 本地',
  fallbackModels: [],
  activeModelId: () => undefined,
})

const models = await adapter.listModels('ninfer')
console.log(JSON.stringify({ models }, null, 1))

// 一次真实请求：确认 adapter 能把 8080 的引擎用起来
const chunks = []
const stream = adapter.stream({
  model: (models[0] && (models[0].id || models[0])) || 'j27b',
  messages: [{ role: 'user', content: '用一句话说明你是谁。' }],
  maxTokens: 64,
})
for await (const ch of stream) {
  if (ch && ch.type === 'block-end' && ch.block) chunks.push(JSON.stringify(ch.block).slice(0, 120))
  if (ch && ch.type === 'finish') { chunks.push('finish:' + JSON.stringify(ch)); break }
}
console.log(JSON.stringify({ events: chunks.slice(0, 4) }, null, 1))
