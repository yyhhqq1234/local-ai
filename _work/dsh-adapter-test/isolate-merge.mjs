// 判定：把 system 合并进 user（不用 system role）是否能恢复可读输出
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1670
const child = spawn(EXE, [MODEL, '--max-context', '16384', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
  { windowsHide: true, stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (let i = 0; i < 300; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
console.log('engine up')

async function ask(tag, messages, maxTok = 64) {
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
  console.log(`[${tag}] HTTP=${r.status} out=${t.length} cjk=${cjk} junk=${junk}  ${JSON.stringify(t.slice(0, 100))}`)
}

const U = '用中文一句话回答：1+1 等于几？'
const S = '你是石井，本地工作区执行层。中文、简短、直接。'

await ask('A 合并到 user（短设定）', [{ role: 'user', content: S + '\n\n' + U }])
await ask('B 合并到 user（长设定×40）', [{ role: 'user', content: S.repeat(40) + '\n\n' + U }])
await ask('C 模拟多轮（合并）', [
  { role: 'user', content: S + '\n\n你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: U },
])
await ask('D system+user 对照（应乱）', [{ role: 'system', content: S }, { role: 'user', content: U }])

child.kill('SIGKILL')
console.log('engine killed')
