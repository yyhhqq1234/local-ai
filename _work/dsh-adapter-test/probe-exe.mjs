import { existsSync } from 'node:fs'
const cands = [
  'D:/BaiduNetdiskDownload/Local-AI/_tools/infer-build/apps/ninfer-serve.exe',
  'D:/BaiduNetdiskDownload/Local-AI/_tools/infer-build/apps/infer-serve.exe',
  'D:\\BaiduNetdiskDownload\\Local-AI\\_tools\\infer-build\\apps\\ninfer-serve.exe',
]
for (const c of cands) console.log(existsSync(c), JSON.stringify(c))
