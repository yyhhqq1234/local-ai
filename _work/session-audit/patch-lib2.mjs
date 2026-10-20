// 第二轮瘦身：工具 21→13、技能名限量、system 段去重（TAG 块 + markdown 章节）
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

// 1) 工具白名单收敛到 13 个（去掉 subagent/subagent_fork/present/ops_replace/todo_write/ask_user_question/ops_inspect_local_file/web_fetch）
const OLD_ALLOW = "  toolAllowlist: ['write', 'read', 'edit', 'ops_bash', 'pwsh', 'ops_glob', 'ops_grep', 'ops_inspect_local_file', 'ops_replace', 'skill', 'todo_write', 'ask_user_question', 'present', 'subagent', 'subagent_fork', 'web_search', 'web_fetch', 'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params'],"
const NEW_ALLOW = "  toolAllowlist: ['write', 'read', 'edit', 'ops_bash', 'ops_glob', 'ops_grep', 'skill', 'web_search', 'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params'],"
rep('tool-allowlist', OLD_ALLOW, NEW_ALLOW)

// 2) 加 slimSystem / skillNameLimit 配置
rep('default-config-slim',
  "  slimSkills: true," + NL + "  defaultEffort: 'minimal',",
  "  slimSkills: true," + NL +
  "  slimSystem: true," + NL +
  "  skillNameLimit: 60," + NL +
  "  defaultEffort: 'minimal',")

// 3) adapter 构造传参
rep('adapter-ctor2',
  "      slimSkills: cfg.slimSkills," + NL + "      defaultEffort: cfg.defaultEffort,",
  "      slimSkills: cfg.slimSkills," + NL +
  "      slimSystem: cfg.slimSystem," + NL +
  "      skillNameLimit: cfg.skillNameLimit," + NL +
  "      defaultEffort: cfg.defaultEffort,")

// 4) stream：system 处理加 dedupe（在 slimSkillsBlock 之后）
rep('stream-slim',
  "        if (m.role === 'system' && typeof m.content === 'string') m.content = slimSkillsBlock(m.content)",
  "        if (m.role === 'system' && typeof m.content === 'string') {" + NL +
  "          m.content = slimSkillsBlock(m.content, this.profile.skillNameLimit)" + NL +
  "          if (this.profile.slimSystem !== false) m.content = dedupeSystem(m.content)" + NL +
  "        }")

// 5) slimSkillsBlock 支持上限
rep('slim-skills-limit',
  "function slimSkillsBlock(system) {",
  "function slimSkillsBlock(system, limit) {")

rep('slim-skills-names',
  "    if (!names.length) break",
  "    if (!names.length) break" + NL +
  "    const capped = names.slice(0, limit > 0 ? limit : names.length)")

rep('slim-skills-repl',
  "    const repl = '- 可用技能（' + names.length + ' 个，按需用 skill 工具加载；描述已省略以省前缀）：' + nl + names.map((n) => '  ' + BT + n + BT).join(' · ') + nl",
  "    const tail = names.length > capped.length ? nl + '（另 ' + (names.length - capped.length) + ' 个未列出，用 find-skills 检索）' : ''" + NL +
  "    const repl = '- 可用技能（共 ' + names.length + ' 个，按需用 skill 工具加载；描述已省略）：' + nl + capped.map((n) => '  ' + BT + n + BT).join(' · ') + tail + nl")

// 6) 新增 dedupeSystem（TAG 块去重 + markdown 同名同内容章节去重），插在 toOpenAITools 之前
rep('dedupe-system',
  "function toOpenAITools(tools) {",
  "function dedupeSystem(system) {" + NL +
  "  const NLx = String.fromCharCode(10)" + NL +
  "  let out = String(system)" + NL +
  "  // a) [TAG] ... [/TAG] 块：同名 TAG 只保留第一份" + NL +
  "  const tagRe = /\\[([A-Za-z0-9:_. -]{3,80})\\]([\\s\\S]*?)\\[\\/\\1\\]/g" + NL +
  "  const seenTag = new Set()" + NL +
  "  out = out.replace(tagRe, (whole, tag) => {" + NL +
  "    const key = tag.trim().toLowerCase()" + NL +
  "    if (seenTag.has(key)) return ''" + NL +
  "    seenTag.add(key)" + NL +
  "    return whole" + NL +
  "  })" + NL +
  "  // b) markdown 同名且内容完全相同的章节只留一份" + NL +
  "  const lines = out.split(NLx)" + NL +
  "  const blocks = []" + NL +
  "  let cur = null" + NL +
  "  for (const line of lines) {" + NL +
  "    if (/^#{1,3} /.test(line)) {" + NL +
  "      if (cur) blocks.push(cur)" + NL +
  "      cur = { head: line.trim(), body: [] }" + NL +
  "    } else {" + NL +
  "      if (!cur) cur = { head: '', body: [] }" + NL +
  "      cur.body.push(line)" + NL +
  "    }" + NL +
  "  }" + NL +
  "  if (cur) blocks.push(cur)" + NL +
  "  const norm = (t) => t.replace(/\\s+/g, ' ').trim()" + NL +
  "  const seenHead = new Map()" + NL +
  "  const kept = []" + NL +
  "  for (const b of blocks) {" + NL +
  "    const body = norm(b.body.join(NLx))" + NL +
  "    if (b.head && seenHead.has(b.head) && seenHead.get(b.head) === body) continue" + NL +
  "    if (b.head) seenHead.set(b.head, body)" + NL +
  "    kept.push(b.head ? [b.head, ...b.body].join(NLx) : b.body.join(NLx))" + NL +
  "  }" + NL +
  "  return kept.join(NLx).replace(new RegExp(NLx + '{3,}', 'g'), NLx + NLx)" + NL +
  "}" + NL + NL +
  "function toOpenAITools(tools) {")

fs.writeFileSync(P + '.bak-think2', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
