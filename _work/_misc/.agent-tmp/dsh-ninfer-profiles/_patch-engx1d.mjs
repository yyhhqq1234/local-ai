import fs from 'node:fs'
const P = 'lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = 'Local-AI/_tools/infer-build/apps'
const to = 'Local-AI/_tools/ninfer-build/apps'
const n = s.split(from).length - 1
if (n !== 2) throw new Error('expected 2 occurrences, got ' + n)
s = s.split(from).join(to)
fs.writeFileSync(P, s, 'utf8')
console.log('fixed engineDir paths:', n)
