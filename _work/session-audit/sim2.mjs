// v2 瘦身模拟：12 工具 + 技能名限 60 + system 段去重，实测冷 TTFT
import fs from 'node:fs'

const NL = String.fromCharCode(10)
const BT = String.fromCharCode(96)
const L = fs.readFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/session.jsonl', 'utf8').split('\n').filter(Boolean)
const sysRaw = JSON.parse(L[10]).data.message.content.map((b) => b.text || '').join(NL)
const toolsAll = JSON.parse(L[17]).data.header.tools

const ALLOW = ['write', 'read', 'edit', 'ops_bash', 'ops_glob', 'ops_grep', 'skill', 'web_search',
  'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params']

function slimSkillsBlock(system, limit) {
  const OPEN = '<available_skills>', CLOSE = '</available_skills>'
  let out = String(system), i
  while ((i = out.indexOf(OPEN)) >= 0) {
    const j = out.indexOf(CLOSE, i)
    if (j < 0) break
    const body = out.slice(i + OPEN.length, j)
    const names = body.split(NL).map((l) => l.trim())
      .filter((l) => l.startsWith('- ' + BT))
      .map((l) => { const a = l.indexOf(BT); const b = l.indexOf(BT, a + 1); return a >= 0 && b > a ? l.slice(a + 1, b) : '' })
      .filter(Boolean)
    if (!names.length) break
    const capped = names.slice(0, limit > 0 ? limit : names.length)
    const tail = names.length > capped.length ? NL + '（另 ' + (names.length - capped.length) + ' 个未列出，用 find-skills 检索）' : ''
    const repl = '- 可用技能（共 ' + names.length + ' 个，按需用 skill 工具加载；描述已省略）：' + NL + capped.map((n) => '  ' + BT + n + BT).join(' · ') + tail + NL
    out = out.slice(0, i) + repl + out.slice(j + CLOSE.length)
  }
  return out
}

function dedupeSystem(system) {
  let out = String(system)
  const tagRe = /\[([A-Za-z0-9:_. -]{3,80})\]([\s\S]*?)\[\/\1\]/g
  const seenTag = new Set()
  out = out.replace(tagRe, (whole, tag) => {
    const key = tag.trim().toLowerCase()
    if (seenTag.has(key)) return ''
    seenTag.add(key)
    return whole
  })
  const lines = out.split(NL)
  const blocks = []
  let cur = null
  for (const line of lines) {
    if (/^#{1,3} /.test(line)) { if (cur) blocks.push(cur); cur = { head: line.trim(), body: [] } }
    else { if (!cur) cur = { head: '', body: [] }; cur.body.push(line) }
  }
  if (cur) blocks.push(cur)
  const norm = (t) => t.replace(/\s+/g, ' ').trim()
  const seenHead = new Map()
  const kept = []
  for (const b of blocks) {
    const body = norm(b.body.join(NL))
    if (b.head && seenHead.has(b.head) && seenHead.get(b.head) === body) continue
    if (b.head) seenHead.set(b.head, body)
    kept.push(b.head ? [b.head, ...b.body].join(NL) : b.body.join(NL))
  }
  return kept.join(NL).replace(new RegExp(NL + '{3,}', 'g'), NL + NL + NL)
}

const sysSlim = dedupeSystem(slimSkillsBlock(sysRaw, 60))
const toolsKept = toolsAll.filter((t) => ALLOW.includes(t.name || t.function?.name))
const prefix = [sysSlim, JSON.stringify(toolsKept)].join(NL + NL)

console.log('system  :', sysRaw.length, '->', sysSlim.length)
console.log('tools   :', toolsAll.length, '->', toolsKept.length, '| bytes', JSON.stringify(toolsAll).length, '->', JSON.stringify(toolsKept).length)
console.log('prefix  :', prefix.length)

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
console.log(JSON.stringify({ label: 'V2', ttftMs: first, promptTokens: usage?.prompt_tokens, text: text.slice(0, 8) }))
