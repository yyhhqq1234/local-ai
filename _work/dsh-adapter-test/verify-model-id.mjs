// 验证：引擎在跑 → 列表来自引擎；引擎停 → 列表给当前档位现行模型（不是硬编码 27B）
import { NinferManager } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
const adapterFallback = () => {
  const f = m.activeModelFile()
  return f ? f.replace(/\.ninfer$/i, '') : undefined
}

for (const profile of ['csunx-27b', 'build-9b']) {
  m.writeParams({ profile })
  console.log(profile.padEnd(11), '→ activeModelId =', adapterFallback(), '| file =', m.activeModelFile())
}
m.writeParams({ profile: 'csunx-27b', port: 1234, vision: 'cpu' })
console.log('------------------')
console.log('引擎实际在跑的（端口 1234）:')
const r = await fetch('http://127.0.0.1:1234/v1/models').then((x) => x.json()).catch((e) => ({ error: String(e) }))
console.log(JSON.stringify(r))
