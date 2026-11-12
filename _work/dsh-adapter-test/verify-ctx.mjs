// 端到端验证：16384 上下文 + 预算裁剪 + 真实 DSH 体量 prompt（54K 字符）
import { NinferManager } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
m.writeParams({ profile: 'build-9b', port: 1660, vision: 'off', reasoningEffort: 'none' })
const t0 = Date.now()
const st = await m.start({})
console.log('start ok =', st.running, 'ready', ((Date.now() - t0) / 1000).toFixed(1) + 's',
  'ctx =', st.contextWindow, 'model =', st.model)

async function chat(prompt, maxTok) {
  const body = JSON.stringify({
    model: st.model,
    messages: [{ role: 'system', content: '你是本地助手。' }, { role: 'user', content: prompt }],
    max_tokens: maxTok, temperature: 0, stream: false,
  })
  const r = await fetch('http://127.0.0.1:1660/v1/chat/completions', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body,
  })
  const j = await r.json()
  return { status: r.status, j }
}

// ① 小 prompt
let a = await chat('用一句话说明你是谁。', 32)
console.log('small  :', a.status, 'content_len=' + String(a.j?.choices?.[0]?.message?.content ?? '').length)

// ② 模拟 DSH 体量：52K 字符（约等于截图里 54K）
const big = '背景材料（自动生成，用于测试上下文预算）：' + '本地推理引擎需要在有限显存下运行，'.repeat(1800)
console.log('big prompt chars =', big.length)
let b = await chat(big, 64)
console.log('big    :', b.status, b.status === 200
  ? 'content_len=' + String(b.j?.choices?.[0]?.message?.content ?? '').length + ' tok=' + b.j?.usage?.completion_tokens
  : JSON.stringify(b.j).slice(0, 200))

await m.stop()
console.log('stopped')
