import fs from 'node:fs'
const files = [
  'D:/BaiduNetdiskDownload/Local-AI/_tools/run-serve.ps1',
  'D:/BaiduNetdiskDownload/Local-AI/_tools/accept_final.ps1',
  'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js',
]
for (const f of files) {
  const s = fs.readFileSync(f, 'utf8')
  const hits = [...s.matchAll(/[A-Za-z0-9_\\/.-]*(?:infer-build|infer-serve)[A-Za-z0-9_.\\/-]*/g)].map((m) => m[0])
  console.log('---', f.split('/').slice(-1)[0])
  for (const h of new Set(hits)) console.log('   ', JSON.stringify(h))
}
