// 对照：同一个产物，开思考（不加 --no-thinking）vs 关思考，300 字总结是否还退化
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const P = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const SENT = ['本地推理引擎需要在有限显存下运行。', '权重按层切分后逐块加载到显存。', 'KV 缓存以页为单位分配。',
  'prefill 阶段按一百二十八 token 分块处理。', '生成阶段每步只处理一个 token。']
const natural = (n) => { let s = ''; let i = 0; while (s.length < n * 1.6) s += SENT[i++ % SENT.length]; return s.slice(0, Math.floor(n * 1.6)) }
const prompt300 = '请用一句话总结这段内容：' + natural(190)

async function bench(port, noThink, tag) {
  const args = [P, '--max-context', '16384', '--port', String(port), '--greedy',
    '--host-context-mib', '2048', '--prefill-chunk', '128']
  if (noThink) args.push('--no-thinking')
  const child = spawn(EXE, args, { windowsHide: true, stdio: 'ignore' })
  let up = false
  for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${port}/v1/models`); up = true; break } catch {} }
  if (!up) { console.log(tag, 'not ready'); child.kill(); return }
  const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages: [{ role: 'user', content: prompt300 }], max_tokens: 128, temperature: 0, stream: false })
  const r = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  const j = await r.json()
  const c = j?.choices?.[0]?.message?.content ?? ''
  const rc = j?.choices?.[0]?.message?.reasoning_content ?? ''
  const cjk = (c.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (c.match(/[A-Za-z]{8,}/g) || []).length
  console.log(`[${tag}] content=${c.length} cjk=${cjk} junk=${junk} reasoning=${rc.length}`)
  console.log('   content:', JSON.stringify(c.slice(0, 160)))
  if (rc) console.log('   reasoning:', JSON.stringify(rc.slice(0, 120)))
  child.kill('SIGKILL')
  await sleep(1500)
}

await bench(1677, true, '关思考 --no-thinking')
await bench(1678, false, '开思考（默认模板）')
console.log('done')
