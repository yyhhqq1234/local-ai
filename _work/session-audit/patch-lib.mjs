// 把本地瘦身逻辑打进 lib/index.js（运行时产物），避开 shell 转义：全程不用反斜杠。
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

// 0) fs 导入补 appendFileSync
rep('import-fs',
  "import { closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'",
  "import { appendFileSync, closeSync, existsSync, mkdirSync, openSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs'")

// 1) 默认配置加瘦身项
rep('default-config',
  "  registerAdapter: false," + NL + "  fallbackModels: [{",
  "  registerAdapter: false," + NL +
  "  // —— 本地模型专属瘦身（只作用于 ninfer 这一路请求；云端 provider 各有 adapter，不经过这里）——" + NL +
  "  toolAllowlist: ['write', 'read', 'edit', 'ops_bash', 'pwsh', 'ops_glob', 'ops_grep', 'ops_inspect_local_file', 'ops_replace', 'skill', 'todo_write', 'ask_user_question', 'present', 'subagent', 'subagent_fork', 'web_search', 'web_fetch', 'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params']," + NL +
  "  slimSkills: true," + NL +
  "  defaultEffort: 'minimal'," + NL +
  "  statsPath: 'D:/BaiduNetdiskDownload/Local-AI/_work/session-audit/ninfer-stats.jsonl'," + NL +
  "  fallbackModels: [{")

// 2) 默认思考强度
rep('default-effort',
  "          defaultEffort: 'high',",
  "          defaultEffort: this.profile.defaultEffort ?? 'minimal',")

// 3) adapter 构造传参
rep('adapter-ctor',
  "    const adapter = new NinferAdapter({" + NL +
  "      baseURL: cfg.baseURL," + NL +
  "      displayName: cfg.displayName," + NL +
  "      fallbackModels: cfg.fallbackModels," + NL +
  "      emitReasoning: cfg.emitReasoning," + NL +
  "      timeoutMs: 8000," + NL +
  "    })",
  "    const adapter = new NinferAdapter({" + NL +
  "      baseURL: cfg.baseURL," + NL +
  "      displayName: cfg.displayName," + NL +
  "      fallbackModels: cfg.fallbackModels," + NL +
  "      emitReasoning: cfg.emitReasoning," + NL +
  "      timeoutMs: 8000," + NL +
  "      toolAllowlist: cfg.toolAllowlist," + NL +
  "      slimSkills: cfg.slimSkills," + NL +
  "      defaultEffort: cfg.defaultEffort," + NL +
  "      statsPath: cfg.statsPath || undefined," + NL +
  "    })")

// 4) stream：折叠 skills
rep('stream-messages',
  "    const body = {" + NL +
  "      model: options.model," + NL +
  "      messages: toOpenAIMessages(options),",
  "    const messages = toOpenAIMessages(options)" + NL +
  "    if (this.profile.slimSkills !== false) {" + NL +
  "      for (const m of messages) {" + NL +
  "        if (m.role === 'system' && typeof m.content === 'string') m.content = slimSkillsBlock(m.content)" + NL +
  "      }" + NL +
  "    }" + NL +
  "    const body = {" + NL +
  "      model: options.model," + NL +
  "      messages,")

// 5) stream：工具裁剪 + payload 统计
rep('stream-tools',
  "    const tools = toOpenAITools(options.tools)" + NL +
  "    if (tools) body.tools = tools" + NL +
  "    if (options.reasoningEffort) body.reasoning_effort = String(options.reasoningEffort)",
  "    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))" + NL +
  "    if (tools) body.tools = tools" + NL +
  "    if (options.reasoningEffort) body.reasoning_effort = String(options.reasoningEffort)" + NL +
  "    if (this.profile.statsPath) {" + NL +
  "      try {" + NL +
  "        const systemChars = messages.reduce((a, m) => a + (m.role === 'system' && typeof m.content === 'string' ? m.content.length : 0), 0)" + NL +
  "        appendFileSync(this.profile.statsPath, JSON.stringify({ ts: Date.now(), model: options.model, tools: tools?.length ?? 0, systemChars, payloadBytes: JSON.stringify(body).length }) + String.fromCharCode(10))" + NL +
  "      } catch { /* 统计失败不影响主链路 */ }" + NL +
  "    }")

// 6) 工具函数
rep('helper-fns',
  "function toOpenAITools(tools) {",
  "function matchAllow(name, allow) {" + NL +
  "  for (const rule of allow) {" + NL +
  "    if (rule.endsWith('*')) { if (name.startsWith(rule.slice(0, -1))) return true }" + NL +
  "    else if (name === rule) return true" + NL +
  "  }" + NL +
  "  return false" + NL +
  "}" + NL + NL +
  "function filterTools(tools, allow) {" + NL +
  "  if (!Array.isArray(tools) || tools.length === 0) return tools" + NL +
  "  if (!Array.isArray(allow) || allow.length === 0) return tools" + NL +
  "  const kept = tools.filter((t) => matchAllow(t.name, allow))" + NL +
  "  return kept.length ? kept : tools" + NL +
  "}" + NL + NL +
  "function slimSkillsBlock(system) {" + NL +
  "  const OPEN = '<available_skills>', CLOSE = '</available_skills>'" + NL +
  "  let out = String(system), i" + NL +
  "  while ((i = out.indexOf(OPEN)) >= 0) {" + NL +
  "    const j = out.indexOf(CLOSE, i)" + NL +
  "    if (j < 0) break" + NL +
  "    const body = out.slice(i + OPEN.length, j)" + NL +
  "    const names = body.split(String.fromCharCode(10)).map((l) => l.trim()).filter((l) => l.startsWith('- ' + String.fromCharCode(96))).map((l) => {" + NL +
  "      const a = l.indexOf(String.fromCharCode(96))" + NL +
  "      const b = l.indexOf(String.fromCharCode(96), a + 1)" + NL +
  "      return a >= 0 && b > a ? l.slice(a + 1, b) : ''" + NL +
  "    }).filter(Boolean)" + NL +
  "    if (!names.length) break" + NL +
  "    const nl = String.fromCharCode(10)" + NL +
  "    const BT = String.fromCharCode(96)" + NL +
  "    const repl = '- 可用技能（' + names.length + ' 个，按需用 skill 工具加载；描述已省略以省前缀）：' + nl + names.map((n) => '  ' + BT + n + BT).join(' · ') + nl" + NL +
  "    out = out.slice(0, i) + repl + out.slice(j + CLOSE.length)" + NL +
  "  }" + NL +
  "  return out" + NL +
  "}" + NL + NL +
  "function toOpenAITools(tools) {")

fs.writeFileSync(P + '.bak-think', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
