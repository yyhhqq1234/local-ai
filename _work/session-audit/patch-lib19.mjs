// 修 offload 递归：read/ops_grep 等"内容型"工具的输出不再落盘（否则落盘→read→再落盘 死循环）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to); done.push(name)
}

// 1) 调用处：先建 tool_call_id → 工具名 映射
rep('offload-mapid',
  '    if (this.profile.offloadToolResultMaxChars > 0) {' + NL +
  '      offloadLargeToolResults(messages, this.profile.offloadToolResultMaxChars, this.profile.offloadDir)' + NL +
  '    }',
  '    if (this.profile.offloadToolResultMaxChars > 0) {' + NL +
  '      const toolNameById = new Map()' + NL +
  '      for (const om of (options.messages || [])) {' + NL +
  "        if (om.role !== 'assistant' || !Array.isArray(om.content)) continue" + NL +
  '        for (const ob of om.content) {' + NL +
  "          if (ob && ob.type === 'tool-call' && ob.id) toolNameById.set(String(ob.id), String(ob.name || ''))" + NL +
  '        }' + NL +
  '      }' + NL +
  '      offloadLargeToolResults(messages, this.profile.offloadToolResultMaxChars, this.profile.offloadDir, toolNameById)' + NL +
  '    }')

// 2) 实现：跳过内容型工具
rep('offload-skip',
  'function offloadLargeToolResults(messages, maxChars, dir) {' + NL +
  '  for (const m of messages) {' + NL +
  "    if (m.role !== 'tool' || typeof m.content !== 'string') continue",
  'function offloadLargeToolResults(messages, maxChars, dir, toolNameById) {' + NL +
  '  const NO_OFFLOAD = new Set(["read", "ops_grep", "ops_glob", "ops_inspect_local_file", "edit", "write"])' + NL +
  '  for (const m of messages) {' + NL +
  "    if (m.role !== 'tool' || typeof m.content !== 'string') continue" + NL +
  '    const tname = toolNameById && m.tool_call_id ? toolNameById.get(String(m.tool_call_id)) : ""' + NL +
  '    if (tname && NO_OFFLOAD.has(tname)) continue')

// 3) executionRules 增加一条（避免模型主动 read 回刚落盘的内容）
rep('rules-no-readback',
  "'6) 临时文件放 _tmp/，任务结束删掉，不在工作区留垃圾。',",
  "'6) 临时文件放 _tmp/，任务结束删掉，不在工作区留垃圾。'," + NL +
  "  '7) 工具输出里带「已落盘: <path>」的，说明摘要已足够判断，不要立刻 read 回来；确需原始细节再读，且只读一次。',")

fs.writeFileSync(P + '.bak-think19', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
