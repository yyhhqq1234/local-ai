// 1) 把 6 个脚本里的 oxcoder9b-merged 全部指向新产物；2) 备份旧 conversion.json 作记录；3) 删产物
import fs from 'node:fs'

const ROOT = 'D:/BaiduNetdiskDownload/Local-AI'
const OLD_FILE = 'oxcoder9b-merged.ninfer'
const NEW_FILE = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
const OLD_ID = 'oxcoder9b-merged'
const NEW_ID = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'

const scripts = ['accept_final.ps1', 'accept5.ps1', 'bench_decode.ps1', 'cas_tools.ps1', 'probe_dsh.ps1', 'repro-attn.ps1']
for (const s of scripts) {
  const p = ROOT + '/_tools/' + s
  let t = fs.readFileSync(p, 'utf8')
  const before = (t.split(OLD_FILE).length - 1) + (t.split(OLD_ID).length - 1)
  if (!before) { console.log('skip', s, '(0 refs)'); continue }
  fs.copyFileSync(p, p + '.bak-merged-del')
  t = t.split(OLD_FILE).join(NEW_FILE)     // 先换长名（含 OLD_ID 前缀，避免二次替换）
  t = t.split("'" + OLD_ID + "'").join("'" + NEW_ID + "'")
  fs.writeFileSync(p, t, 'utf8')
  console.log('patched', s, 'refs=' + before)
}

// 备份 conversion.json 作历史记录（很小），再删产物
const outDir = ROOT + '/train/lines/9b-oxcoder/out/'
const recDir = ROOT + '/_work/ninfer-9b/removed-artifacts/'
fs.mkdirSync(recDir, { recursive: true })
if (fs.existsSync(outDir + OLD_FILE + '.conversion.json')) {
  fs.copyFileSync(outDir + OLD_FILE + '.conversion.json', recDir + OLD_FILE + '.conversion.json')
  console.log('kept record:', recDir + OLD_FILE + '.conversion.json')
}
const target = outDir + OLD_FILE
if (fs.existsSync(target)) {
  const size = fs.statSync(target).size
  fs.rmSync(target)
  console.log('deleted', target, (size / 2 ** 30).toFixed(2) + ' GiB')
} else {
  console.log('already gone:', target)
}
const cj = outDir + OLD_FILE + '.conversion.json'
if (fs.existsSync(cj)) { fs.rmSync(cj); console.log('deleted', cj) }
