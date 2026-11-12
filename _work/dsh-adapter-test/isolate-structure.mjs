// 判定：是"多轮结构"坏还是"长文本"坏
import { spawn } from 'node:child_process'
const EXE = 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe'
const MODEL = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/9b-oxcoder/out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const PORT = 1673
const child = spawn(EXE, [MODEL, '--max-context', '16384', '--port', String(PORT), '--greedy',
  '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking'], { windowsHide: true, stdio: 'ignore' })
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
for (let i = 0; i < 300; i++) { await sleep(400); try { await fetch(`http://127.0.0.1:${PORT}/v1/models`); break } catch {} }
console.log('engine up')

async function ask(tag, messages, maxTok = 96) {
  const body = JSON.stringify({ model: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ', messages, max_tokens: maxTok, temperature: 0, stream: false })
  const r = await fetch(`http://127.0.0.1:${PORT}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body })
  const j = await r.json()
  const t = j?.choices?.[0]?.message?.content ?? ''
  const cjk = (t.match(/[\u4e00-\u9fa5]/g) || []).length
  const junk = (t.match(/[A-Za-z]{8,}/g) || []).length
  const ok = cjk >= 8 && junk === 0 ? 'PASS' : 'FAIL'
  console.log(`[${ok}] ${tag}  out=${t.length} cjk=${cjk} junk=${junk}  ${JSON.stringify(t.slice(0, 90))}`)
}

// a) 自然长 user（非重复内容）
await ask('a 自然长user(约420字)', [{ role: 'user', content:
  '下面是一段背景说明，请读完后用一句话总结它讲了什么：本地推理引擎要在 12GB 显卡上运行 9B 模型，' +
  '权重占 8.69GiB，KV 缓存按页分配，prefill 必须分块到 128 否则 L03 层的 K/V 投影会出现 NaN，' +
  '输出速度约 32 token/s，冷启动约 7 秒，上下文目前设为 16384 token。请只用一句中文回答。' }])

// b) 多轮（无 system）
await ask('b 多轮(无system)', [
  { role: 'user', content: '你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: '用中文一句话回答：1+1 等于几？' },
], 48)

// c) 多轮 + system
await ask('c 多轮+system', [
  { role: 'system', content: '你是助手，用中文简短回答。' },
  { role: 'user', content: '你好' },
  { role: 'assistant', content: '你好，我在。' },
  { role: 'user', content: '用中文一句话回答：1+1 等于几？' },
], 48)

// d) 单条 user 但内容里带"角色扮演"式前缀（模拟合并后的 system）
await ask('d 单条user含设定', [{ role: 'user', content:
  '【系统设定】你是助手，用中文简短回答。【用户问题】用中文一句话回答：1+1 等于几？' }], 48)

child.kill('SIGKILL')
console.log('engine killed')
