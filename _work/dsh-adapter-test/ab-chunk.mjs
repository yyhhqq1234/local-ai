// 关键假设：prefill 块宽恰为 16 的倍数（128）会走坏分支 → 长 prompt 退化
// 验证：chunk 128（16×8） vs 120 / 112 / 96（非 16 倍数）
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const P = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const SENT = ['本地推理引擎需要在有限显存下运行。', '权重按层切分后逐块加载到显存。', 'KV 缓存以页为单位分配。',
  'prefill 阶段按一百二十八 token 分块处理。', '生成阶段每步只处理一个 token。', '量化会带来精度损失。']
const natural = (n) => { let s = ''; let i = 0; while (s.length < n * 1.6) s += SENT[i++ % SENT.length]; return s.slice(0, Math.floor(n * 1.6)) }
const prompt300 = '请用一句话总结这段内容：' + natural(190)
const prompt600 = '请用一句话总结这段内容：' + natural(390)

async function bench(chunk, port) {
  const child = spawn(EXE, [P, '--max-context', '16384', '--port', String(port), '--greedy',
    '--host-context-mib', '2048', '--prefill-chunk', String(chunk), '--no-thinking'], { windowsHide: true, stdio: 'ignore' })
  let up = false
  for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${port}/v1/models`); up = true; break } catch {} }
  if (!up) { console.log(`chunk=${chunk} NOT READY`); child.kill(); return }
  for (const [tag, prompt] of [['300字', prompt300], ['600字', prompt600]]) {
    const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages: [{ role: 'user', content: prompt }], max_tokens: 96, temperature: 0, stream: false })
    const r = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
    const j = await r.json()
    const c = j?.choices?.[0]?.message?.content ?? ''
    const cjk = (c.match(/[\u4e00-\u9fa5]/g) || []).length
    const junk = (c.match(/[A-Za-z]{8,}/g) || []).length
    const verdict = cjk >= 10 && junk <= 1 ? 'PASS' : 'FAIL'
    console.log(`  ${verdict} chunk=${chunk} ${tag} out=${c.length} cjk=${cjk} junk=${junk} ${JSON.stringify(c.slice(0, 70))}`)
  }
  child.kill('SIGKILL')
  await sleep(1500)
}

for (const [i, chunk] of [128, 120, 112, 96].entries()) {
  await bench(chunk, 1680 + i)
}
console.log('done')
