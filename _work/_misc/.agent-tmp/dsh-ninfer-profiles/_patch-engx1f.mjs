// src/index.ts 同步：工具参数补 profile（lib 已生效，src 保持可重建一致）
import fs from 'node:fs'
const P = 'src/index.ts'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

rep('engine tool profile',
  "      vision: { type: 'string', description: 'off | cpu | overlay' },\n      port: { type: 'number', description: '引擎端口' },",
  "      vision: { type: 'string', description: 'off | cpu | overlay' },\n      port: { type: 'number', description: '引擎端口' },\n      profile: { type: 'string', description: '引擎档位：csunx-27b（默认，27B launcher）| build-9b（9B 直启）' },")

rep('params tool profile',
  "      vision: { type: 'string' },\n      port: { type: 'number' },\n      restartNow: { type: 'boolean' },",
  "      vision: { type: 'string' },\n      port: { type: 'number' },\n      profile: { type: 'string' },\n      restartNow: { type: 'boolean' },")

rep('pickParams profile',
  "      if (typeof args.kvDtype === 'string') patch.kvDtype = args.kvDtype as never",
  "      if (typeof args.profile === 'string') patch.profile = args.profile\n      if (typeof args.kvDtype === 'string') patch.kvDtype = args.kvDtype as never")

fs.writeFileSync(P, s, 'utf8')
console.log('src/index.ts synced: ' + hits.join(', '))
