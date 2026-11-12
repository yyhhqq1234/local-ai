import { existsSync, readdirSync } from 'node:fs'
const dirs = [
  'D:/BaiduNetdiskDownload/Local-AI/_tools/infer-build/apps',
  'D:\\BaiduNetdiskDownload\\Local-AI\\_tools\\infer-build\\apps',
]
for (const d of dirs) {
  try {
    const files = readdirSync(d).filter((f) => f.toLowerCase().endsWith('.exe'))
    console.log('OK', JSON.stringify(d), '->', files.map((f) => JSON.stringify(f)).join(' '))
    for (const f of files) console.log('   exists full:', existsSync(d + '/' + f), JSON.stringify(f))
  } catch (e) {
    console.log('ERR', JSON.stringify(d), e.code, e.message)
  }
}
