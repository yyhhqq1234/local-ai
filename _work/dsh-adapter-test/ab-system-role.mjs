// 判定：system 角色本身是否损坏；合并进 user 是否可行
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1693
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const child = spawn(EXE, [MODEL, '--max-context', '8192', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'], { windowsHide: true, stdio: 'ignore' })
for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
console.log('engine up')

const U = '用中文一句话回答：1+1 等于几？'
const S = '你是助手，中文简短。'
async function ask(tag, messages, maxTok = 48) {
  const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages, max_tokens: maxTok, temperature: 0, stream: false })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  const j = await r.json()
  const c = j?.choices?.[0]?.message?.content ?? ''
  const junk = (c.match(/[A-Za-z]{8,}/g) || []).length
  const hasTwo = /2|二/.test(c)
  console.log(`[${hasTwo && junk === 0 ? 'PASS' : 'FAIL'}] ${tag} out=${c.length} junk=${junk} ${JSON.stringify(c.slice(0, 80))}`)
}

await ask('1 user-only', [{ role: 'user', content: U }])
await ask('2 system+user', [{ role: 'system', content: S }, { role: 'user', content: U }])
await ask('3 merged(设定在前)', [{ role: 'user', content: S + '\n\n' + U }])
await ask('4 multi-turn 无system', [
  { role: 'user', content: '你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: U },
])
await ask('5 median-turn + merged', [
  { role: 'user', content: S + '\n\n你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: U },
])
child.kill('SIGKILL')
console.log('done')
