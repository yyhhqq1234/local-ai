// 用真实 DSH 体量输入走适配器（compactSystem 生效），看输出是否可读
import { NinferManager, NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
import { readFileSync, existsSync } from 'node:fs'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
m.writeParams({ profile: 'build-9b', port: 1690, vision: 'off', reasoningEffort: 'none' })
const st = await m.start({})
console.log('engine ready ctx =', st.contextWindow)

const prof = {
  baseURL: 'http://127.0.0.1:1690/v1',
  displayName: 'test',
  contextBudget: { window: 16384, maxOutput: 1024, reserve: 256 },
  compactSystem: true,
  compactSystemText: '你是石井，本地工作区执行层。中文、简短、直接；先给结论后给理由。',
  compactHistoryMessages: 6,
  slimSkills: false, slimSystem: false, emitReasoning: true,
  defaultEffort: 'none', effortCap: 'none', fallbackModels: [], timeoutMs: 8000,
}
const adapter = new NinferAdapter(prof)

const conv = existsSync('C:/Users/Administrator/.dsh/AGENTS.md') ? readFileSync('C:/Users/Administrator/.dsh/AGENTS.md', 'utf8') : '约定'
const ws = existsSync('D:/BaiduNetdiskDownload/Local-AI/AGENTS.md') ? readFileSync('D:/BaiduNetdiskDownload/Local-AI/AGENTS.md', 'utf8') : ''
const skills = '<available_skills>\n' + Array.from({ length: 120 }, (_, i) => `- \`skill-${i}\`: 示例技能描述占位。`).join('\n') + '\n</available_skills>'
const system = [conv, ws, skills, conv].join('\n\n')
const txt = (x) => [{ type: 'text', text: x }]

async function run(tag, messages, maxTok = 256) {
  let text = '', finish = '', err = ''
  try {
    for await (const ev of adapter.stream({
      model: st.model, messages, maxTokens: maxTok, temperature: 0,
      reasoningEffort: 'none', tools: undefined, stop: undefined,
    })) {
      if (ev.type === 'text-delta' && typeof ev.text === 'string') text += ev.text
      if (ev.type === 'finish') finish = JSON.stringify(ev.reason)
    }
  } catch (e) { err = String(e && e.message).slice(0, 160) }
  const cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (text.match(/[A-Za-z]{8,}/g) || []).length
  console.log(`[${cjk >= 6 && junk <= 1 ? 'PASS' : 'FAIL'}] ${tag} out=${text.length} cjk=${cjk} junk=${junk} fin=${finish} ${err}`)
  console.log('   ', JSON.stringify(text.slice(0, 120)))
}

await run('DSH体量+你好', [{ role: 'system', content: txt(system) }, { role: 'user', content: txt('你好') }])
await run('DSH体量+1+1', [{ role: 'system', content: txt(system) }, { role: 'user', content: txt('1+1 等于几？只回数字') }], 64)
await run('多轮', [
  { role: 'system', content: txt(system) },
  { role: 'user', content: txt('你好') },
  { role: 'assistant', content: txt('你好，我在。') },
  { role: 'user', content: txt('用一句话说明本地推理引擎的作用。') },
], 256)

await m.stop()
