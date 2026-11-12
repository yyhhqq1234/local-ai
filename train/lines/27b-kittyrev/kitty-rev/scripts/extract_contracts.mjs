#!/usr/bin/env node
/**
 * extract_contracts.mjs —— 从 kitty-toolbox（只读）抽取真实契约，落到本工作区 contracts/
 *
 * 只读源：D:\DrCE(26.2.16)\kitty-toolbox\src\{tool-manifest.ts, ops-catalog.ts, actions-session.ts}
 * 只写目标：train/lines/27b-kittyrev/kitty-rev/contracts/
 *
 * 用途：后训练数据必须建立在真实工具名 / 真实 OP 语法 / 真实错误码上，
 *      不能用模型编的接口（历史事故：41 步自造桥接脚本）。
 *
 * 用法：node extract_contracts.mjs [--src <kitty根>]
 */
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const OUT = resolve(HERE, '..', 'contracts')
const DEFAULT_SRC = 'D:\\DrCE(26.2.16)\\kitty-toolbox'

const argv = process.argv.slice(2)
const srcArg = argv.indexOf('--src')
const SRC = srcArg >= 0 ? argv[srcArg + 1] : DEFAULT_SRC

function read(p) {
  try { return readFileSync(p, 'utf8') } catch { return '' }
}

const manifestTxt = read(join(SRC, 'src', 'tool-manifest.ts'))
const opsTxt = read(join(SRC, 'src', 'ops-catalog.ts'))
const sessionTxt = read(join(SRC, 'src', 'actions-session.ts'))

if (!manifestTxt || !opsTxt) {
  console.error(`[FATAL] 读不到契约源：${SRC}\\src\\{tool-manifest.ts,ops-catalog.ts}`)
  console.error('        确认 DrCE 目录存在且只读可访问；本脚本不写入该目录。')
  process.exit(1)
}

/* ---------- 1. 工具表 ---------- */
const tools = []
const toolRe = /\{\s*name:\s*'([^']+)',\s*channel:\s*'([^']+)',\s*actions:\s*\[([^\]]*)\](?:,\s*ops:\s*\[([^\]]*)\])?,\s*description:\s*'([^']*)'\s*\}/g
let m
while ((m = toolRe.exec(manifestTxt))) {
  const parseList = (s) => (s || '').split(',').map((x) => x.trim().replace(/^'|'$/g, '')).filter(Boolean)
  tools.push({ name: m[1], channel: m[2], actions: parseList(m[3]), ops: parseList(m[4]), description: m[5] })
}

/* ---------- 2. OP 冻结表 ---------- */
const ops = []
const opRe = /\{\s*op:\s*'([^']+)',\s*sig:\s*'((?:[^'\\]|\\.)*)',\s*reply:\s*'((?:[^'\\]|\\.)*)'(?:,\s*note:\s*'((?:[^'\\]|\\.)*)')?\s*\}/g
while ((m = opRe.exec(opsTxt))) {
  ops.push({
    op: m[1],
    sig: m[2].replace(/\\'/g, "'"),
    reply: m[3].replace(/\\'/g, "'"),
    note: (m[4] || '').replace(/\\'/g, "'"),
  })
}

const hotIdx = opsTxt.indexOf('HOT_OPS')
const hotTxt = hotIdx >= 0 ? opsTxt.slice(hotIdx, hotIdx + 600) : ''
const hotOps = [...hotTxt.matchAll(/'([A-Z_]{2,})'/g)].map((x) => x[1]).slice(1, 13)

const verM = opsTxt.match(/BRIDGE_VERSION\s*=\s*'([^']+)'/)

/* ---------- 3. taskTransition 合法集合 ---------- */
const tmM = sessionTxt.match(/TYPE_SET\s*=\s*\[([^\]]*)\]/)
const transitions = tmM ? [...tmM[1].matchAll(/'([^']+)'/g)].map((x) => x[1]) : []

/* ---------- 4. 错误码（从 TS 里抓 ERR|xxx） ---------- */
const errCodes = [...new Set([
  ...(manifestTxt + opsTxt + sessionTxt).matchAll(/ERR\|([A-Za-z0-9_-]+)/g),
].map((x) => x[1]))].sort()

/* ---------- 落盘 ---------- */
mkdirSync(OUT, { recursive: true })
const stamp = new Date().toISOString()
const common = { src: SRC, extractedAt: stamp, bridge: verM ? verM[1] : 'unknown' }

writeFileSync(join(OUT, 'tools.json'), JSON.stringify({ ...common, count: tools.length, tools }, null, 2), 'utf8')
writeFileSync(join(OUT, 'ops.json'), JSON.stringify({ ...common, count: ops.length, hot: hotOps, ops }, null, 2), 'utf8')
writeFileSync(join(OUT, 'transitions.json'), JSON.stringify({ ...common, count: transitions.length, types: transitions, errCodes }, null, 2), 'utf8')

console.log(`[ok] tools=${tools.length} ops=${ops.length} hot=${hotOps.length} transitions=${transitions.length} errCodes=${errCodes.length}`)
console.log(`     bridge=${verM ? verM[1] : '?'}`)
console.log(`     out=${OUT}`)
if (tools.length < 30) console.log('[WARN] 工具数偏少，manifest 解析规则可能已变，检查 src/tool-manifest.ts 格式')
if (ops.length < 40) console.log('[WARN] OP 数偏少，catalog 解析规则可能已变，检查 src/ops-catalog.ts 格式')
