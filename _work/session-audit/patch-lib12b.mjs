// 零损提速 patch v2（锚点修正）
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []

function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to)
  done.push(name)
}

rep('cfg-offload',
  '  executionRules: "## 本地执行纪律',
  '  offloadToolResultMaxChars: 2000,   // 超过该字符数的工具输出落盘，上下文只留头尾（无损可回溯）' + NL +
  '  offloadDir: "D:/BaiduNetdiskDownload/Local-AI/_work/toolout",' + NL +
  '  executionRules: "## 本地执行纪律')

rep('ctor-offload',
  '      executionRules: cfg.executionRules,',
  '      executionRules: cfg.executionRules,' + NL +
  '      offloadToolResultMaxChars: cfg.offloadToolResultMaxChars,' + NL +
  '      offloadDir: cfg.offloadDir,')

rep('call-offload',
  '    if (this.profile.executionRules) {',
  '    if (this.profile.offloadToolResultMaxChars > 0) {' + NL +
  '      offloadLargeToolResults(messages, this.profile.offloadToolResultMaxChars, this.profile.offloadDir)' + NL +
  '    }' + NL +
  '    if (this.profile.executionRules) {')

const impl = [
  'function offloadLargeToolResults(messages, maxChars, dir) {',
  '  for (const m of messages) {',
  "    if (m.role !== 'tool' || typeof m.content !== 'string') continue",
  '    if (m.content.length <= maxChars) continue',
  '    const total = m.content.length',
  '    const head = m.content.slice(0, Math.floor(maxChars * 0.6))',
  '    const tail = m.content.slice(-Math.floor(maxChars * 0.25))',
  '    let path = ""',
  '    try {',
  '      fsMod.mkdirSync(dir, { recursive: true })',
  '      const name = "toolout-" + String(m.tool_call_id || Date.now()).replace(/[^A-Za-z0-9_-]/g, "").slice(-16) + "-" + total + ".log"',
  '      path = dir + "/" + name',
  '      fsMod.writeFileSync(path, m.content, "utf8")',
  '    } catch (e) { path = "" }',
  '    const note = path',
  '      ? "[完整输出 " + total + " 字符已落盘: " + path + " —— 需要细节时用 read 工具按行读取]"',
  '      : "[输出过长已裁剪，共 " + total + " 字符]"',
  '    m.content = head + String.fromCharCode(10) + "..." + String.fromCharCode(10) + note + String.fromCharCode(10) + "..." + String.fromCharCode(10) + tail',
  '  }',
  '}',
].join(NL)

rep('impl-offload', 'function toOpenAITools(tools) {', impl + NL + NL + 'function toOpenAITools(tools) {')

rep('import-fs',
  "import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'",
  "import * as fsMod from 'node:fs'" + NL +
  "import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'")

fs.writeFileSync(P + '.bak-think12', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
