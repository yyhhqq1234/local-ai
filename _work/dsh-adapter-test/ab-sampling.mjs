// 最后一项判定：greedy 坍缩？换采样（temperature>0）能否救回 system+user
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1694
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const child = spawn(EXE, [MODEL, '--max-context', '8192', '--port', String(PORT),
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'], { windowsHide: true, stdio: 'ignore' })
for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
console.log('engine up (no --greedy)')

const U = '用中文一句话回答：1+1 等于几？'
const S = '你是助手，中文简短。'
async function ask(tag, messages, opts = {}) {
  const body = JSON.stringify({
    model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages,
    max_tokens: opts.maxTok ?? 48,
    temperature: opts.t ?? 0,
    ...(opts.topP ? { top_p: opts.topP } : {}),
    ...(opts.rep ? { frequency_penalty: opts.rep } : {}),
    stream: false,
  })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  const j = await r.json()
  const c = j?.choices?.[0]?.message?.content ?? ''
  const junk = (c.match(/[A-Za-z]{6,}/g) || []).length
  const ok = /等于\s*2|是\s*2|2。/.test(c) && junk <= 1
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${tag} out=${c.length} junk=${junk} ${JSON.stringify(c.slice(0, 70))}`)
}

const msgs = [{ role: 'system', content: S }, { role: 'user', content: U }]
await ask('t=0', msgs, { t: 0 })
await ask('t=0.3 topP=0.9', msgs, { t: 0.3, topP: 0.9 })
await ask('t=0.7 topP=0.9 rep=0.3', msgs, { t: 0.7, topP: 0.9, rep: 0.3 })
await ask('user-only t=0.7', [{ role: 'user', content: U }], { t: 0.7, topP: 0.9 })
child.kill('SIGKILL')
console.log('done')
