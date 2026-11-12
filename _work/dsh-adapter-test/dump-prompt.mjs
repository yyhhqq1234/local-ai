// 落盘两种结构的渲染后 prompt，逐字对比
import { spawn } from 'node:child_process'
import { rmSync, readFileSync } from 'node:fs'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const DUMP = 'D:/BaiduNetdiskDownload/Local-AI/_tools/prompt-dump.txt'
const PORT = 1695
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
try { rmSync(DUMP) } catch {}

const child = spawn(EXE, [MODEL, '--max-context', '8192', '--port', String(PORT),
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
  { windowsHide: true, stdio: 'ignore', env: { ...process.env, NINFER_DUMP_PROMPT: DUMP } })
for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }

async function ask(messages, maxTok = 8) {
  const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages, max_tokens: maxTok, temperature: 0, stream: false })
  await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  await sleep(400)
}

const U = '用中文一句话回答：1+1 等于几？'
await ask([{ role: 'user', content: U }])
await ask([{ role: 'system', content: '你是助手，中文简短。' }, { role: 'user', content: U }])
await ask([
  { role: 'user', content: '你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: U },
])
child.kill('SIGKILL')
await sleep(500)

const raw = readFileSync(DUMP, 'utf8')
const parts = raw.split('\n=====REQ=====\n').filter(Boolean)
console.log('渲染次数 =', parts.length)
parts.forEach((p, i) => {
  console.log('\n########## 请求', i + 1, '长度', p.length)
  console.log(JSON.stringify(p))
})
