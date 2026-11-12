// 复刻 DSH 真实体量：system 35398 字符 + 历史 → 验证裁剪后不再 400
import { NinferManager, NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
m.writeParams({ profile: 'build-9b', port: 1663, vision: 'off', reasoningEffort: 'none' })
const st = await m.start({})
console.log('engine ready:', st.running, 'ctx =', st.contextWindow)

const adapter = new NinferAdapter({
  baseURL: 'http://127.0.0.1:1663/v1',
  displayName: 'test',
  contextBudget: { window: 16384, maxOutput: 2048, reserve: 512 },
  slimSkills: false, slimSystem: false, emitReasoning: true,
  defaultEffort: 'none', effortCap: 'medium', fallbackModels: [], timeoutMs: 8000,
})

const txt = (s) => [{ type: 'text', text: s }]
// 用真实 DSH 约定段的体量：35398 字符 system
const sysText = ('[工作区约定片段] 你是本地执行层。产出物首行即交付物。' .repeat(900)).slice(0, 35398)
const messages = [
  { role: 'system', content: txt(sysText) },
  { role: 'user', content: txt('你好') },
]
const chars = messages.reduce((a, x) => a + x.content[0].text.length, 0)
console.log('输入 chars =', chars, '≈', Math.ceil(chars / 1.7), 'tokens（窗口 16384，预算 13824）')

let text = ''
let finish = ''
try {
  for await (const ev of adapter.stream({
    model: st.model, messages, maxTokens: 2048, temperature: 0,
    reasoningEffort: 'none', tools: undefined, stop: undefined,
  })) {
    if (ev.type === 'text-delta' && typeof ev.text === 'string') text += ev.text
    if (ev.type === 'finish') finish = JSON.stringify(ev.reason)
  }
  console.log('OK content =', JSON.stringify(text.slice(0, 60)), 'finish =', finish)
} catch (e) {
  console.log('FAIL', String(e && e.message).slice(0, 240))
}
await m.stop()
console.log('stopped')
