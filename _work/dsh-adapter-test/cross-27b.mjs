// 27B 产物 + 我方 ninfer-master 引擎：system/多轮是否同样乱码
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/ninfer-27b-kv-stream-3arch-20261019/model/qwen3.8-27b-kittyrev-v6-iq2s-mtp.ninfer'
const PORT = 1696
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const child = spawn(EXE, [MODEL, '--max-context', '4096', '--port', String(PORT),
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
  { windowsHide: true, stdio: 'ignore' })

let up = false
for (let i = 0; i < 500; i++) { await sleep(500); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); up = true; break } catch {} }
if (!up) { console.log('ENGINE NOT READY'); child.kill(); process.exit(1) }
const id = (await (await fetch(`http://127.0.0.1:${PORT}/v1/models`)).json()).data[0].id
console.log('engine up, model id =', id)

const U = '用中文一句话回答：1+1 等于几？'
async function ask(tag, messages, maxTok = 64) {
  const body = JSON.stringify({ model: id, messages, max_tokens: maxTok, temperature: 0, stream: false })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  const j = await r.json()
  const c = j?.choices?.[0]?.message?.content ?? ''
  const cjk = (c.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (c.match(/[A-Za-z]{8,}/g) || []).length
  const good = /2|二/.test(c) && junk === 0
  console.log(`[${good ? 'PASS' : 'FAIL'}] ${tag} HTTP=${r.status} out=${c.length} cjk=${cjk} junk=${junk}`)
  console.log('   ', JSON.stringify(c.slice(0, 120)))
}

await ask('1 user-only', [{ role: 'user', content: U }], 32)
await ask('2 system+user', [{ role: 'system', content: '你是助手，中文简短。' }, { role: 'user', content: U }], 32)
await ask('3 multi-turn', [
  { role: 'user', content: '你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: U },
], 32)

child.kill('SIGKILL')
await sleep(800)
console.log('done')
