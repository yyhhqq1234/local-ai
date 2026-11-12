// 走适配器真实路径（DSH block 格式）：验证 trimToBudget 把 ~60K 字符压进 16384 上下文
import { NinferManager, NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
m.writeParams({ profile: 'build-9b', port: 1662, vision: 'off', reasoningEffort: 'none' })
const st = await m.start({})
console.log('engine ready:', st.running, 'ctx =', st.contextWindow)

const adapter = new NinferAdapter({
  baseURL: 'http://127.0.0.1:1662/v1',
  displayName: 'test',
  contextBudget: { window: 16384, maxOutput: 2048, reserve: 512 },
  slimSkills: false,
  slimSystem: false,
  emitReasoning: true,
  defaultEffort: 'none',
  effortCap: 'medium',
  fallbackModels: [],
  timeoutMs: 8000,
})

const txt = (s) => [{ type: 'text', text: s }]
const big = (n) => '这是一段用于撑大上下文的背景材料，包含若干本地推理细节。'.repeat(n)

const messages = [
  { role: 'system', content: txt('你是本地执行层。') },
  { role: 'user', content: txt('旧消息 A：' + big(500)) },
  { role: 'assistant', content: txt('旧回复 A') },
  { role: 'user', content: txt('旧消息 B：' + big(500)) },
  { role: 'assistant', content: txt('旧回复 B') },
  { role: 'user', content: txt('现在只回答：1+1 等于几？只回数字。') },
]
const chars = messages.reduce((a, x) => a + x.content[0].text.length, 0)
console.log('输入 chars =', chars, '≈', Math.ceil(chars / 1.7), 'tokens（窗口 16384）')

let text = ''
let finish = ''
try {
  for await (const ev of adapter.stream({
    model: st.model, messages, maxTokens: 2048, temperature: 0,
    reasoningEffort: 'none', tools: undefined, stop: undefined,
  })) {
    const d = ev && (ev.delta ?? ev.text)
    if (typeof d === 'string' && (ev.type === 'text-delta' || ev.type === 'reasoning-delta')) text += d
    else if (typeof ev.text === 'string' && ev.type === 'text-delta') text += ev.text
    if (ev.type === 'finish') finish = JSON.stringify(ev.reason)
  }
  console.log('OK 输出 =', JSON.stringify(text.slice(0, 80)), 'finish =', finish)
} catch (e) {
  console.log('FAIL', String(e && e.message).slice(0, 300))
}

await m.stop()
console.log('stopped')
