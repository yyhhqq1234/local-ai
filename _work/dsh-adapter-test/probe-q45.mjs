import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const P = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/models/oxcoder-9b-Q4Q5.ninfer'
const PORT = 1676
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const child = spawn(EXE, [P, '--max-context', '8192', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'], { windowsHide: true, stdio: 'ignore' })
for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
const models = await fetch(`http://127.0.0.1:${PORT}/v1/models`).then((r) => r.json()).catch((e) => ({ err: String(e) }))
console.log('models:', JSON.stringify(models))
const id = models?.data?.[0]?.id

const SENT = ['本地推理引擎需要在有限显存下运行。', '权重按层切分后逐块加载到显存。', 'KV 缓存以页为单位分配。', 'prefill 阶段按一百二十八 token 分块处理。', '生成阶段每步只处理一个 token。']
const natural = (n) => { let s = ''; let i = 0; while (s.length < n * 1.6) { s += SENT[i++ % SENT.length] } return s.slice(0, Math.floor(n * 1.6)) }

async function ask(tag, content, maxTok = 64) {
  const body = JSON.stringify({ model: id, messages: [{ role: 'user', content }], max_tokens: maxTok, temperature: 0, stream: false })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  const j = await r.json().catch(() => ({}))
  const t = j?.choices?.[0]?.message?.content ?? ''
  const cjk = (t.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (t.match(/[A-Za-z]{8,}/g) || []).length
  console.log(`[${tag}] HTTP=${r.status} out=${t.length} cjk=${cjk} junk=${junk} ${JSON.stringify(t.slice(0, 80))}`)
}

await ask('短', '用中文一句话回答：1+1 等于几？', 24)
await ask('100字', '请用一句话总结：' + natural(60))
await ask('300字', '请用一句话总结：' + natural(190))
child.kill('SIGKILL')
console.log('killed')
