// 用"真实体量 + 真实内容"验证压缩后是否还出乱码
// system 取本地真实文件拼装（约 35K 字符），再问一个可判定答案的问题
import { NinferManager, NinferAdapter } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
import { readFileSync, existsSync, rmSync } from 'node:fs'

const STATS = 'D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test/stats-compress.jsonl'
try { rmSync(STATS) } catch {}

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
m.writeParams({ profile: 'build-9b', port: 1667, vision: 'off', reasoningEffort: 'none' })
const st = await m.start({})
console.log('engine ready ctx =', st.contextWindow)

const adapter = new NinferAdapter({
  baseURL: 'http://127.0.0.1:1667/v1',
  displayName: 'test',
  contextBudget: { window: 16384, maxOutput: 2048, reserve: 512 },
  slimSkills: false, slimSystem: false, emitReasoning: true,
  defaultEffort: 'none', effortCap: 'none', fallbackModels: [], timeoutMs: 8000,
  statsPath: STATS,
})

// 拼一份"真实形状"的 system：约定段 ×2 + 一大段技能目录
const conv = existsSync('C:/Users/Administrator/.dsh/AGENTS.md')
  ? readFileSync('C:/Users/Administrator/.dsh/AGENTS.md', 'utf8')
  : '你是本地执行层。'
const ws = existsSync('D:/BaiduNetdiskDownload/Local-AI/AGENTS.md')
  ? readFileSync('D:/BaiduNetdiskDownload/Local-AI/AGENTS.md', 'utf8') : ''
const skills = '<available_skills>\n' + Array.from({ length: 120 }, (_, i) =>
  `- \`skill-${i}\`: 这是一个示例技能描述，用于占位测试技能目录的体量。`).join('\n') + '\n</available_skills>'
const system = [conv, ws, skills, conv].join('\n\n')

const txt = (s) => [{ type: 'text', text: s }]
const messages = [
  { role: 'system', content: txt(system) },
  { role: 'user', content: txt('回答两个问题：1+1 等于几？用中文一句话回答。') },
]
console.log('system chars =', system.length, '≈', Math.ceil(system.length / 1.7), 'tokens')

let text = '', finish = '', reasonErr = ''
try {
  for await (const ev of adapter.stream({
    model: st.model, messages, maxTokens: 128, temperature: 0,
    reasoningEffort: 'none', tools: undefined, stop: undefined,
  })) {
    if (ev.type === 'text-delta' && typeof ev.text === 'string') text += ev.text
    if (ev.type === 'finish') finish = JSON.stringify(ev.reason)
  }
} catch (e) { reasonErr = String(e && e.message).slice(0, 200) }

console.log('输出长度 =', text.length, 'finish =', finish, reasonErr ? 'ERR ' + reasonErr : '')
console.log('输出 =', JSON.stringify(text.slice(0, 200)))

// 乱码判据：中文占比 + 是否含明显随机拉丁串
const cjk = (text.match(/[\u4e00-\u9fa5]/g) || []).length
const latinRun = (text.match(/[A-Za-z]{12,}/g) || []).length
console.log(`判据：中文字数=${cjk} 长拉丁串=${latinRun} → ${cjk >= 5 && latinRun <= 1 ? 'PASS（可读）' : 'FAIL（疑似退化）'}`)

if (existsSync(STATS)) {
  const lines = readFileSync(STATS, 'utf8').trim().split('\n')
  const j = JSON.parse(lines[lines.length - 1])
  console.log('实际 payloadBytes =', j.payloadBytes, ' systemChars =', j.systemChars)
}
await m.stop()
