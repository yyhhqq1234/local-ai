// 决定性对照：同一引擎，同一 system 内容，三种喂法，看谁出乱码
import { spawn } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'

const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1668
const child = spawn(EXE, [MODEL, '--max-context', '16384', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
  { windowsHide: true, stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (let i = 0; i < 300; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
console.log('engine up')

const conv = existsSync('C:/Users/Administrator/.dsh/AGENTS.md') ? readFileSync('C:/Users/Administrator/.dsh/AGENTS.md', 'utf8') : '你是本地执行层。'
const ws = existsSync('D:/BaiduNetdiskDownload/Local-AI/AGENTS.md') ? readFileSync('D:/BaiduNetdiskDownload/Local-AI/AGENTS.md', 'utf8') : ''

const skillBlock = (n) => '<available_skills>\n' + Array.from({ length: n }, (_, i) =>
  `- \`skill-${i}\`: 示例技能描述，用于占位测试技能目录体量。`).join('\n') + '\n</available_skills>'

async function ask(tag, system, user, maxTok = 96) {
  const body = JSON.stringify({
    model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ',
    messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    max_tokens: maxTok, temperature: 0, stream: false,
  })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body,
  })
  const j = await r.json()
  const t = j?.choices?.[0]?.message?.content ?? ''
  const cjk = (t.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (t.match(/[A-Za-z]{10,}/g) || []).length
  console.log(`\n[${tag}] sysChars=${system.length} HTTP=${r.status} out=${t.length} cjk=${cjk} junkLatin=${junk}`)
  if (r.status !== 200) console.log('   ', JSON.stringify(j).slice(0, 160))
  else console.log('   ', JSON.stringify(t.slice(0, 140)))
}

const user = '回答：1+1 等于几？用中文一句话回答。'

// A: 极简 system
await ask('A 极简system', '你是本地执行层，用中文简短回答。', user)

// B: 真实约定（约 19K 字符，未压缩，能塞进 16384）
await ask('B 真实约定未压缩', [conv, ws].join('\n\n'), user)

// C: 真实约定 + 技能目录（超预算，需要压缩）
await ask('C 约定+技能目录', [conv, ws, skillBlock(120), conv].join('\n\n'), user)

// D: C 的压缩版（模拟 adapter 的结构化压缩）
function compressSystem(text, budgetChars) {
  let t = text.replace(/<available_skills>[\s\S]*?<\/available_skills>/g, '[技能目录已省略]')
  const seen = new Set(); const kept = []
  for (const p of t.split(/\n{2,}/)) {
    const k = p.slice(0, 80).replace(/\s+/g, ' ').trim()
    if (k && seen.has(k)) continue
    if (k) seen.add(k)
    kept.push(p)
  }
  t = kept.join('\n\n')
  if (t.length > budgetChars) t = t.slice(0, budgetChars) + '\n\n[... 尾部截断 ...]'
  return t
}
await ask('D 压缩版', compressSystem([conv, ws, skillBlock(120), conv].join('\n\n'), Math.floor(13824 * 0.85 * 1.7)), user)

child.kill('SIGKILL')
console.log('\nengine killed')
