// 模拟设置页会拿到的 /state 载荷（不发 HTTP，直接问 manager）
import { NinferManager } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
const st = await m.status()
const payload = {
  running: st.running,
  pid: st.pid,
  baseURL: st.baseURL,
  model: st.model,
  contextWindow: st.contextWindow,
  params: st.params,
  profile: st.profile,
  profiles: st.profiles,
  engine: st.engine,
  activeModelFile: st.modelFile,
  models: m.listModels().map((x) => ({ file: x.file, gib: +(x.bytes / 2 ** 30).toFixed(2), profile: x.profile })),
  logs: st.logs,
}
console.log(JSON.stringify(payload, null, 1))
