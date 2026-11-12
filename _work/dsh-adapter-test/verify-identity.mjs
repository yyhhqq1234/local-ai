// 双引擎区分验证：身份、模型归属、停引擎不误杀
import { NinferManager } from 'file:///D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'

const m = new NinferManager('D:/BaiduNetdiskDownload/Local-AI/_work/dsh-adapter-test')
const log = (...a) => console.log(...a)

log('=== 1) 两个引擎的身份 ===')
m.writeParams({ profile: 'csunx-27b' })
log(JSON.stringify(m.engineInfo(), null, 1))
m.writeParams({ profile: 'build-9b' })
log(JSON.stringify(m.engineInfo(), null, 1))

log('=== 2) 模型归属（每条带 profile）===')
for (const x of m.listModels()) log('  ', x.profile.padEnd(11), x.file, (x.bytes / 2 ** 30).toFixed(2) + ' GiB')

log('=== 3) 起 9B，确认只起 9B ===')
m.writeParams({ profile: 'build-9b', port: 1651, vision: 'off' })
const st = await m.start()
log('running =', st.running, 'model =', st.model, 'profile =', st.profile)
log('engine.exe =', st.engine.exe)
log('engine.label =', st.engine.label)

log('=== 4) stop() 之后进程表 ===')
await m.stop()
await new Promise((r) => setTimeout(r, 1500))
const after = await m.status()
log('engine answering =', after.running)
