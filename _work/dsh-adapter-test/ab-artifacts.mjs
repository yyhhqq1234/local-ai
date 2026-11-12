// A/B：G1 q8 产物 vs Q4Q5 产物（同基座另一次量化），同 prompt 比可读性
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODELS = {
  G1: ['D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer', 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'],
  Q45: ['D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/models/oxcoder-9b-Q4Q5.ninfer', 'oxcoder-9b-Q4Q5'],
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const SENT = [
  '本地推理引擎需要在有限显存下运行。',
  '权重按层切分后逐块加载到显存。',
  'KV 缓存以页为单位分配，页大小是六十四 token。',
  'prefill 阶段按一百二十八 token 分块处理。',
  '注意力层的投影输出必须保持数值稳定。',
  '生成阶段每步只处理一个 token。',
  '量化会带来精度损失，需要评测确认。',
  '上下文窗口决定了可以记住多少内容。',
  '冷启动时间主要由权重加载决定。',
  '多模态需要额外的视觉编码器。',
]

function natural(nTokens) {
  // 目标约 nTokens 个 token；中文约 1.6 字/token
  const targetChars = Math.floor(nTokens * 1.6)
  let s = ''
  let i = 0
  while (s.length < targetChars) { s += SENT[i % SENT.length]; i++ }
  return s.slice(0, targetChars)
}

async function bench(tag, [modelPath, modelId], port) {
  const child = spawn(EXE, [modelPath, '--max-context', '16384', '--port', String(port), '--greedy',
    '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'], { windowsHide: true, stdio: 'ignore' })
  let up = false
  for (let i = 0; i < 400; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${port}/v1/models`); up = true; break } catch {} }
  if (!up) { console.log(`[${tag}] engine NOT ready`); child.kill(); return }
  const ask = async (label, content, maxTok = 64) => {
    const body = JSON.stringify({ model: modelId, messages: [{ role: 'user', content }], max_tokens: maxTok, temperature: 0, stream: false })
    const r = await fetch(`http://127.0.0.1:${port}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
    const j = await r.json()
    const t = j?.choices?.[0]?.message?.content ?? ''
    const cjk = (t.match(/[\u4e00-\u9fa5]/g) || []).length
    const junk = (t.match(/[A-Za-z]{8,}/g) || []).length
    console.log(`  ${cjk >= 8 && junk === 0 ? 'PASS' : 'FAIL'} [${tag}/${label}] in=${content.length}字 out=${t.length} cjk=${cjk} junk=${junk} ${JSON.stringify(t.slice(0, 70))}`)
  }
  await ask('短问题', '用中文一句话回答：1+1 等于几？', 24)
  await ask('自然100字', '请用一句话总结这段内容：' + natural(60), 48)
  await ask('自然300字', '请用一句话总结这段内容：' + natural(190), 64)
  await ask('自然620字', '请用一句话总结这段内容：' + natural(390), 64)
  child.kill('SIGKILL')
  await sleep(1500)
}

console.log('=== G1 q8 产物 ===')
await bench('G1', MODELS.G1, 1674)
console.log('=== Q4Q5 产物 ===')
await bench('Q45', MODELS.Q45, 1675)
console.log('done')
