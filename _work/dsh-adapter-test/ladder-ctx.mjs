// 阶梯实验：确认引擎 16384 下 prompt+max_tokens 的真实边界
import { spawn } from 'node:child_process'
import { readFileSync, existsSync } from 'node:fs'

const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1665
const LOG = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ladder.log'
import { rmSync } from 'node:fs'
try { rmSync(LOG); rmSync(LOG + '.err') } catch {}

const child = spawn(EXE, [MODEL, '--max-context', '16384', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
  { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
let out = ''
child.stdout.on('data', (d) => { out += d })
child.stderr.on('data', (d) => { out += d })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (let i = 0; i < 300; i++) {
  await sleep(400)
  try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {}
}
console.log('engine up')

const zh = (n) => '本地推理引擎需要在有限显存下运行，参数与上下文都要按实测来定。'.repeat(Math.ceil(n / 30)).slice(0, n)

async function probe(chars, maxTok) {
  const sys = zh(chars)
  const body = JSON.stringify({
    model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ',
    messages: [{ role: 'system', content: sys }, { role: 'user', content: '你好' }],
    max_tokens: maxTok, temperature: 0, stream: false,
  })
  const t0 = Date.now()
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body,
  })
  const j = await r.json()
  const m = out.match(/req#\d+ done \|[^\n]*?prompt ([\d,]+)/g)
  const last = m ? m[m.length - 1] : ''
  console.log(`chars=${chars} maxTok=${maxTok} → HTTP ${r.status}` +
    (r.status === 200 ? ` prompt=${(j.usage?.prompt_tokens ?? '?')} out=${j.usage?.completion_tokens}` : ` ${JSON.stringify(j).slice(0, 120)}`) +
    ` [${Date.now() - t0}ms]`)
}

await probe(4000, 512)
await probe(12000, 512)
await probe(16000, 512)
await probe(20000, 512)
await probe(24000, 512)
await probe(20000, 4096)
child.kill('SIGKILL')
console.log('engine killed')
