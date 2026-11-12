// 决定性：同一产物，比较 4096 与 16384 两种 max-context 下的输出质量
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function run(ctx, port) {
  const child = spawn(EXE, [MODEL, '--max-context', String(ctx), '--port', String(port), '--greedy',
    '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'],
    { windowsHide: true, stdio: 'ignore' })
  for (let i = 0; i < 300; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${port}/v1/models`); break } catch {} }

  const ask = async (tag, messages, maxTok = 64) => {
    const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages, max_tokens: maxTok, temperature: 0, stream: false })
    const r = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, {
      method: 'POST', headers: { 'content-type': 'application/json' }, body })
    const j = await r.json()
    const t = j?.choices?.[0]?.message?.content ?? ''
    const cjk = (t.match(/[\u4e00-\u9fa5]/g) || []).length
    const junk = (t.match(/[A-Za-z]{8,}/g) || []).length
    console.log(`  [ctx=${ctx} ${tag}] HTTP=${r.status} out=${t.length} cjk=${cjk} junk=${junk}  ${JSON.stringify(t.slice(0, 80))}`)
  }

  await ask('1 短问答', [{ role: 'user', content: '用中文一句话回答：1+1 等于几？' }], 32)
  await ask('2 带system', [{ role: 'system', content: '你是助手，用中文简短回答。' }, { role: 'user', content: '用中文一句话回答：1+1 等于几？' }], 32)
  await ask('3 长user(1500字)', [{ role: 'user', content: '请用中文总结下面这段话：' + '本地推理引擎需要在有限显存下运行，参数要按实测来定。'.repeat(60) }], 64)
  child.kill('SIGKILL')
  await sleep(1200)
}

console.log('=== max-context 4096 ===')
await run(4096, 1671)
console.log('=== max-context 16384 ===')
await run(16384, 1672)
console.log('done')
