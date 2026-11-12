// 判定：乱码是否由"带 system 消息"触发
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1669
const child = spawn(EXE, [MODEL, '--max-context', '16384', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
  { windowsHide: true, stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (let i = 0; i < 300; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
console.log('engine up')

const U = '用中文一句话回答：1+1 等于几？'

async function ask(tag, messages, maxTok = 48) {
  const body = JSON.stringify({
    model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ',
    messages, max_tokens: maxTok, temperature: 0, stream: false,
  })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body,
  })
  const j = await r.json()
  const t = j?.choices?.[0]?.message?.content ?? ''
  const cjk = (t.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (t.match(/[A-Za-z]{8,}/g) || []).length
  console.log(`[${tag}] HTTP=${r.status} out=${t.length} cjk=${cjk} junkLatin=${junk}  ${JSON.stringify(t.slice(0, 90))}`)
}

await ask('1 user-only', [{ role: 'user', content: U }])
await ask('2 system+user', [{ role: 'system', content: '你是助手，用中文回答。' }, { role: 'user', content: U }])
await ask('3 system-long-realistic', [{ role: 'system', content: '你是石井，本地工作区执行层。语气中文简短直接，先给产物后解释。'.repeat(30) }, { role: 'user', content: U }])
await ask('4 user-only maxTok128', [{ role: 'user', content: U }], 128)
await ask('5 user-only 你好', [{ role: 'user', content: '你好' }], 48)

child.kill('SIGKILL')
console.log('engine killed')
