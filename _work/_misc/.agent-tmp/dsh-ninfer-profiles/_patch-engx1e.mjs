import fs from 'node:fs'
const P = 'lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = "contextWindow = Number(first.context_window ?? meta.n_ctx ?? 0) || undefined"
const to = "contextWindow = Number(first.context_window ?? first.max_model_len ?? meta.n_ctx ?? 0) || undefined"
const n = s.split(from).length - 1
if (n !== 1) throw new Error('contextWindow anchor count=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('contextWindow: now reads max_model_len too')
