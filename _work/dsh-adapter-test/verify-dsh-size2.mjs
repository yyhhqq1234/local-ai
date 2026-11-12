// 复跑 DSH 体量测试，并让 adapter 写出 payloadBytes，定位 400 的真实体量
import { NinferManager, NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
import { readFileSync, existsSync, rmSync } from 'node:fs'

const STATS = 'D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test/stats-trim.jsonl'
try { rmSync(STATS) } catch {}

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
m.writeParams({ profile: 'build-9b', port: 1666, vision: 'off', reasoningEffort: 'none' })
const st = await m.start({})
console.log('engine ready ctx =', st.contextWindow)

const adapter = new NinferAdapter({
  baseURL: 'http://127.0.0.1:1666/v1',
  displayName: 'test',
  contextBudget: { window: 16384, maxOutput: 2048, reserve: 512 },
  slimSkills: false, slimSystem: false, emitReasoning: true,
  defaultEffort: 'none', effortCap: 'medium', fallbackModels: [], timeoutMs: 8000,
  statsPath: STATS,
})

const txt = (s) => [{ type: 'text', text: s }]
const sysText = ('[工作区约定片段] 你是本地执行层。产出物首行即交付物。'.repeat(900)).slice(0, 35398)
const messages = [{ role: 'system', content: txt(sysText) }, { role: 'user', content: txt('你好') }]
console.log('输入 system chars =', sysText.length)

let text = '', finish = ''
try {
  for await (const ev of adapter.stream({
    model: st.model, messages, maxTokens: 2048, temperature: 0,
    reasoningEffort: 'none', tools: undefined, stop: undefined,
  })) {
    if (ev.type === 'text-delta' && typeof ev.text === 'string') text += ev.text
    if (ev.type === 'finish') finish = JSON.stringify(ev.reason)
  }
  console.log('结果:', JSON.stringify(text.slice(0, 40)), finish)
} catch (e) {
  console.log('FAIL', String(e && e.message).slice(0, 200))
}

if (existsSync(STATS)) {
  const lines = readFileSync(STATS, 'utf8').trim().split('\n')
  const j = JSON.parse(lines[lines.length - 1])
  console.log('实际 payloadBytes =', j.payloadBytes, ' totalChars =', j.totalChars, ' systemChars =', j.systemChars)
}
await m.stop()
