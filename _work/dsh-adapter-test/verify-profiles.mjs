// 适配器多档位行为验证：不碰 ninfer-csunx 的 live 配置，用独立 dir
import { NinferManager } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
import { request } from 'node:http'

const DIR = 'D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test'
const m = new NinferManager(DIR)

function chat(port, model, prompt, maxTokens = 24) {
  return new Promise((res, rej) => {
    const body = JSON.stringify({ model, messages: [{ role: 'user', content: prompt }], max_tokens: maxTokens, temperature: 0, stream: false })
    const req = request({ host: '127.0.0.1', port, path: '/v1/chat/completions', method: 'POST', timeout: 120000,
      headers: { 'content-type': 'application/json', 'content-length': Buffer.byteLength(body) } }, (r) => {
      let b = ''
      r.setEncoding('utf8')
      r.on('data', (c) => { b += c })
      r.on('end', () => { try { res(JSON.parse(b)) } catch { rej(new Error('bad json: ' + b.slice(0, 200))) } })
    })
    req.on('timeout', () => req.destroy(new Error('timeout')))
    req.on('error', rej)
    req.end(body)
  })
}

const out = []
const log = (...a) => { const s = a.join(' '); out.push(s); console.log(s) }

log('=== 1) 默认档位与模型枚举 ===')
log('default params.profile =', m.readParams().profile)
const models = m.listModels()
log('models total =', models.length)
for (const mm of models) log('  ', mm.profile.padEnd(11), mm.file, (mm.bytes / 2 ** 30).toFixed(2) + ' GiB')

log('=== 2) 档位隔离 ===')
m.writeParams({ profile: 'csunx-27b' })
log('csunx-27b active =', m.activeModelFile())
m.writeParams({ profile: 'build-9b' })
log('build-9b  active =', m.activeModelFile(), '(应 = kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer)')

log('=== 3) 直启 9B（独立 dir，端口 1650，不干扰 live 配置）===')
m.writeParams({ profile: 'build-9b', port: 1650, vision: 'off' })
const t0 = Date.now()
const st = await m.start()
log('start ok =', st.running, 'ready in', ((Date.now() - t0) / 1000).toFixed(1) + 's', 'model =', st.model, 'ctx =', st.contextWindow)

log('=== 4) 真实对话 ===')
const r = await chat(1650, st.model, '用一句话说明本地推理引擎的作用。', 24)
const c = r?.choices?.[0]?.message?.content ?? ''
log('content_len =', c.length, 'finish =', r?.choices?.[0]?.finish_reason, 'tok =', r?.usage?.completion_tokens)
log('text =', JSON.stringify(c.slice(0, 60)))

log('=== 5) 停引擎 ===')
await m.stop()
const after = await m.status()
log('running after stop =', after.running)

// 收尾：把测试 dir 的 profile 复原，避免下次误用
m.writeParams({ profile: 'csunx-27b', port: 1234, vision: 'cpu' })
log('=== 测试 dir 已复位 profile=csunx-27b ===')
