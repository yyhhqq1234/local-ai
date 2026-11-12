// 判定：换掉产物自带 chat template 是否修好 system/长 prompt 退化
import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const cands = [
  'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/models/merged-2b-nsfw-mtp-tuned-v3/chat_template.jinja',
  'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx/chat_template_qwen3.8-enhanced.jinja',
]
console.log('template candidates:')
for (const c of cands) console.log('  ', existsSync(c) ? 'FOUND ' : 'missing', c)
const tpl = cands.find((c) => existsSync(c))

async function bench(useTpl, port, tag) {
  const args = [MODEL, '--max-context', '8192', '--port', String(port), '--greedy',
    '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking']
  if (useTpl) args.push('--chat-template', tpl)
  const child = spawn(EXE, args, { windowsHide: true, stdio: 'ignore' })
  let up = false
  for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${port}/v1/models`); up = true; break } catch {} }
  if (!up) { console.log(tag, 'NOT READY'); child.kill(); return }
  const ask = async (label, messages, maxTok = 64) => {
    const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages, max_tokens: maxTok, temperature: 0, stream: false })
    const r = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
    const j = await r.json()
    const c = j?.choices?.[0]?.message?.content ?? ''
    const cjk = (c.match(/[\u4e00-\u9fa5]/g) || []).length
    const junk = (c.match(/[A-Za-z]{8,}/g) || []).length
    console.log(`  ${cjk >= 6 && junk <= 1 ? 'PASS' : 'FAIL'} [${tag}/${label}] out=${c.length} cjk=${cjk} junk=${junk} ${JSON.stringify(c.slice(0, 70))}`)
  }
  const U = '用中文一句话回答：1+1 等于几？'
  await ask('user-only', [{ role: 'user', content: U }], 32)
  await ask('system+user', [{ role: 'system', content: '你是助手，中文简短。' }, { role: 'user', content: U }], 32)
  await ask('长user', [{ role: 'user', content: '请用一句话总结：' + '本地推理引擎在有限显存下运行，参数要按实测确定。'.repeat(12) }], 64)
  child.kill('SIGKILL')
  await sleep(1500)
}

console.log('=== A 产物自带模板 ===')
await bench(false, 1691, 'native-tpl')
if (tpl) { console.log('=== B 外部模板:', tpl, '==='); await bench(true, 1692, 'ext-tpl') }
console.log('done')
