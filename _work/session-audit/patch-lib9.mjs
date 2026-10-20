// 工具-提示一致性：白名单不含 kitty_* 时，把 kitty 的使用说明从上下文里剔除
// 依据：会话 ea3a32d0 turn4 —— 模型 reasoning 明确写“工具列表里没有 kitty_ce”，
// 但系统提示仍在教它怎么调，于是花 41 步找调用路径，最后被用户 abort。
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
const BT = String.fromCharCode(96)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []

function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to)
  done.push(name)
}

// 1) 配置开关
rep('cfg-strip', "  slimSystem: true,", "  slimSystem: true," + NL + "  stripToolHints: ['kitty'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）")

// 2) adapter 构造传参
rep('ctor-strip', "      slimSystem: cfg.slimSystem,", "      slimSystem: cfg.slimSystem," + NL + "      stripToolHints: cfg.stripToolHints,")

// 3) 消息处理里调用
rep('stream-strip',
  "          if (this.profile.slimSystem !== false) m.content = dedupeSystem(m.content)",
  "          if (this.profile.slimSystem !== false) m.content = dedupeSystem(m.content)" + NL +
  "          if (Array.isArray(this.profile.stripToolHints) && this.profile.stripToolHints.length) m.content = stripToolHints(m.content)")

// 4) 实现 stripToolHints（放在 toOpenAITools 之前）
rep('impl-strip',
  'function toOpenAITools(tools) {',
  'function stripToolHints(system, tags) {' + NL +
  '  let out = String(system)' + NL +
  '  for (const tag of tags || []) {' + NL +
  '    // a) [tag-reverse:x ...] ... [/tag-reverse:x] 整块' + NL +
  '    const re = new RegExp(String.fromCharCode(92) + "[" + tag + "-reverse:[^" + String.fromCharCode(92) + "]]*" + String.fromCharCode(92) + "][^" + String.fromCharCode(92) + "]]*?" + String.fromCharCode(92) + "[" + String.fromCharCode(92) + "/" + tag + "-reverse:[^" + String.fromCharCode(92) + "]]*" + String.fromCharCode(92) + "]", "g")' + NL +
  '    out = out.replace(re, "")' + NL +
  '    // b) “X 通道（…文件桥…）” 速查段：从该行起到 API-FREEZE 行结束' + NL +
  '    const head = out.indexOf("A 通道（KittyCE 文件桥")' + NL +
  '    if (tag === "kitty" && head >= 0) {' + NL +
  '      const end = out.indexOf("API-FREEZE.md" + ' + JSON.stringify(BT) + ', head)' + NL +
  '      if (end > head) out = out.slice(0, head) + out.slice(end + 16)' + NL +
  '    }' + NL +
  '  }' + NL +
  '  return out' + NL +
  '}' + NL + NL +
  'function toOpenAITools(tools) {')

// 5) 调用处补参数
rep('call-strip',
  "if (Array.isArray(this.profile.stripToolHints) && this.profile.stripToolHints.length) m.content = stripToolHints(m.content)",
  "if (Array.isArray(this.profile.stripToolHints) && this.profile.stripToolHints.length) m.content = stripToolHints(m.content, this.profile.stripToolHints)")

fs.writeFileSync(P + '.bak-think9', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
