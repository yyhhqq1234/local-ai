import fs from 'node:fs'
const P = 'lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = 'class NinferManager {'
const to = 'export class NinferManager {'
const n = s.split(from).length - 1
if (n !== 1) throw new Error('NinferManager class anchor count=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('exported NinferManager, bytes=' + s.length)
