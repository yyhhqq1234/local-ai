// 核验剥离后 system 还剩哪些关键小节（确认没误删）
import fs from 'node:fs'

const NL = String.fromCharCode(10), BT = String.fromCharCode(96)
const L = fs.readFileSync('D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/s7.jsonl', 'utf8').split(NL).filter(Boolean)
const sys = JSON.parse(L[8]).data.message.content.map((b) => b.text || '').join(NL)

function stripToolHints(system, tags) {
  let out = String(system)
  for (const tag of tags || []) {
    const openTag = String.fromCharCode(91) + tag + '-reverse:'
    const closeTag = String.fromCharCode(91) + '/' + tag + '-reverse:'
    let guard = 0
    while (guard++ < 8) {
      const a = out.indexOf(openTag)
      if (a < 0) break
      const b = out.indexOf(String.fromCharCode(93), a)
      const c = b < 0 ? -1 : out.indexOf(closeTag, b)
      if (c < 0) break
      const d = out.indexOf(String.fromCharCode(93), c)
      if (d < 0) break
      out = out.slice(0, a) + out.slice(d + 1)
    }
    if (tag === 'kitty') {
      const head = out.indexOf('A 通道（KittyCE 文件桥')
      if (head >= 0) {
        const end = out.indexOf('API-FREEZE.md' + BT, head)
        if (end > head) out = out.slice(0, head) + out.slice(end + 16)
      }
    }
    const dropSection = (startMark) => {
      const a = out.indexOf(startMark)
      if (a < 0) return
      const rest = out.slice(a + startMark.length)
      const m = rest.match(/\n#{1,3} /)
      const b = m ? a + startMark.length + m.index : out.length
      out = out.slice(0, a) + out.slice(b)
    }
    if (tag === 'js-reverse') dropSection('### MCP server: js-reverse')
    if (tag === 'jobs') dropSection('# Background task tools')
  }
  return out
}

function dedupeSystem(system) {
  let out = String(system)
  const tagRe = /\[([A-Za-z0-9:_. -]{3,80})\]([\s\S]*?)\[\/\1\]/g
  const seenTag = new Set()
  out = out.replace(tagRe, (whole, tag) => {
    const k = tag.trim().toLowerCase()
    if (seenTag.has(k)) return ''
    seenTag.add(k)
    return whole
  })
  const lines = out.split(NL)
  const blocks = []
  let cur = null
  for (const l of lines) {
    if (/^#{1,3} /.test(l)) { if (cur) blocks.push(cur); cur = { head: l.trim(), body: [] } }
    else { if (!cur) cur = { head: '', body: [] }; cur.body.push(l) }
  }
  if (cur) blocks.push(cur)
  const norm = (s) => s.replace(/\s+/g, ' ').trim()
  const seen = new Map(), kept = []
  for (const b of blocks) {
    const body = norm(b.body.join(NL))
    if (b.head && seen.has(b.head) && seen.get(b.head) === body) continue
    if (b.head) seen.set(b.head, body)
    kept.push(b.head ? [b.head, ...b.body].join(NL) : b.body.join(NL))
  }
  return kept.join(NL).replace(new RegExp(NL + '{3,}', 'g'), NL + NL + NL)
}

const slim = dedupeSystem(stripToolHints(sys, ['kitty', 'js-reverse', 'jobs']))
console.log('原始', sys.length, '→ 剥离+去重后', slim.length, '（省', sys.length - slim.length, '）')
console.log(NL + '=== 剩余标题 ===')
const heads = [...slim.matchAll(/^#{1,3} .+$/gm)].map((m) => m[0])
heads.forEach((h) => console.log(' ', h))
console.log(NL + '=== 关键项存在性 ===')
const must = ['身份', '执行契约', '输出契约', '复核词', '收口', '路由', '本地模型执行约束', '工作区运行参数', '急救暗号']
for (const k of must) console.log(k.padEnd(20), slim.includes(k) ? 'OK' : 'MISSING')
console.log(NL + '=== 应已消失 ===')
for (const k of ['js-reverse', 'Background task tools', 'kitty_ce']) console.log(k.padEnd(24), slim.includes(k) ? 'STILL THERE' : 'gone')
