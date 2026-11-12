// 验证 listModels 目录合并结果（模拟 adapter 拿到的列表）
import { NinferManager } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
const models = m.listModels()
console.log('目录全量 =', models.length)
for (const x of models) {
  console.log('  [' + (x.profile === 'build-9b' ? '9B ' : '27B') + ']', x.file.replace(/\.ninfer$/, ''), (x.bytes / 2 ** 30).toFixed(2) + ' GiB')
}
console.log('--- 引擎在跑的（1234）---')
const live = await fetch('http://127.0.0.1:1234/v1/models').then((r) => r.json()).catch(() => ({}))
console.log(JSON.stringify(live.data?.map((x) => x.id) ?? live))
