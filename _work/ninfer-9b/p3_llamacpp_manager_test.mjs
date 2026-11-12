// p3_llamacpp_manager_test.mjs — 用真实配置验证 llama-cpp 档的管理面（不 spawn、不重启 DSH）
import { NinferManager, NinferAdapter } from '../../plugins/dsh-local-ai/lib/index.js'

const mgr = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/engines/llama-cpp')
const params = mgr.readParams()
console.log('profile =', params.profile)

const st = await mgr.status()
console.log(JSON.stringify({
  running: st.running,
  baseURL: st.baseURL,
  model: st.model,
  profile: st.profile,
  contextWindow: st.contextWindow,
  engine: st.engine,
}, null, 1).slice(0, 600))

try {
  const models = mgr.listModels()
  console.log('listModels:', models.filter((m) => m.profile === 'llama-cpp').map((m) => m.file))
} catch (e) {
  console.log('listModels ERR', e.message)
}
try {
  console.log('activeModelFile:', mgr.activeModelFile())
} catch (e) {
  console.log('activeModelFile ERR', e.message)
}
try {
  const art = await mgr.start()
  console.log('start(): running=' + art.running)
} catch (e) {
  console.log('start() ERR:', e.message)
}



