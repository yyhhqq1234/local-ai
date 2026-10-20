// 模拟「瘦身后」的真实前缀，实测冷 TTFT（只读 session 快照 + 打本地引擎）
import fs from 'node:fs'

const ALLOW = ['write', 'read', 'edit', 'ops_bash', 'pwsh', 'ops_glob', 'ops_grep',
  'ops_inspect_local_file', 'ops_replace', 'skill', 'todo_write', 'ask_user_question',
  'present', 'subagent', 'subagent_fork', 'web_search', 'web_fetch',
  'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params']

const L = fs.readFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/session.jsonl', 'utf8')
  .split('\n').filter(Boolean)
const sys = JSON.parse(L[10]).data.message.content.map((b) => b.text || '').join('\n')
const skillsRaw = (JSON.parse(L[14]).data.content || []).map((b) => b.text || '').join('\n')
const toolsAll = JSON.parse(L[17]).data.header.tools

// 折叠 skills：只留技能名
function slimSkills(system) {
  const OPEN = '<available_skills>', CLOSE = '</available_skills>', NL = String.fromCharCode(10)
  const i = system.indexOf(OPEN)
  if (i < 0) return system
  const j = system.indexOf(CLOSE, i)
  if (j < 0) return system
  const body = system.slice(i + OPEN.length, j)
  const BT = String.fromCharCode(96)
  const names = body.split(NL).map((l) => l.trim())
    .filter((l) => l.startsWith('- ' + BT))
    .map((l) => { const a = l.indexOf(BT); const b = l.indexOf(BT, a + 1); return a >= 0 && b > a ? l.slice(a + 1, b) : '' })
    .filter(Boolean)
  const repl = '- 可用技能（' + names.length + ' 个，按需用 skill 工具加载；描述已省略以省前缀）：' + NL + names.map((n) => '  ' + BT + n + BT).join(' · ') + NL
  return system.slice(0, i) + repl + system.slice(j + CLOSE.length)
}

const sysSlim = slimSkills(sys)
const toolsKept = toolsAll.filter((t) => ALLOW.includes(t.name || t.function?.name))
const toolsJson = JSON.stringify(toolsKept)
const newPrefix = [sysSlim, skillsRaw.replace(/[\s\S]*/, ''), toolsJson].join('\n\n')

console.log('=== 体积对比 ===')
console.log('system   :', sys.length, '->', sysSlim.length)
console.log('skills段 :', (skillsRaw.match(/<available_skills>[\s\S]*?<\/available_skills>/) || [''])[0].length, '-> 折叠')
console.log('tools    :', toolsAll.length, '个 /', JSON.stringify(toolsAll).length, 'B  ->', toolsKept.length, '个 /', toolsJson.length, 'B')
console.log('prefix总 :', (sys.length + skillsRaw.length + JSON.stringify(toolsAll).length), '->', newPrefix.length)

async function ttft(label, prefix) {
  const t0 = Date.now()
  const r = await fetch('http://127.0.0.1:1234/v1/chat/completions', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      model: 'qwen3.8-27b-ablit-swift15-iq2s',
      messages: [{ role: 'system', content: prefix }, { role: 'user', content: '只回答两个字：收到' }],
      max_tokens: 32, temperature: 0, stream: true, stream_options: { include_usage: true },
    }),
  })
  let first = null, usage = null, text = ''
  const dec = new TextDecoder(); let buf = ''
  for await (const chunk of r.body) {
    buf += dec.decode(chunk, { stream: true })
    let k
    while ((k = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, k).trim(); buf = buf.slice(k + 1)
      if (!line.startsWith('data:')) continue
      const p = line.slice(5).trim(); if (p === '[DONE]') continue
      try {
        const j = JSON.parse(p); const d = j.choices?.[0]?.delta
        if (d?.content) { if (first === null) first = Date.now() - t0; text += d.content }
        if (j.usage) usage = j.usage
      } catch {}
    }
  }
  console.log(JSON.stringify({ label, ttftMs: first, promptTokens: usage?.prompt_tokens, text: text.slice(0, 8) }))
}

await ttft('BEFORE(238 tools, skills全量)', fs.readFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/prefix.txt', 'utf8'))
await ttft('AFTER(21 tools, skills折叠)', newPrefix)
