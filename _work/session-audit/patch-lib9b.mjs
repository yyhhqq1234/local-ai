// 工具-提示一致性（v2 锚点修正）：白名单不含 kitty_* 时，剔除 kitty 使用说明
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
const BT = String.fromCharCode(96)
const BS = String.fromCharCode(92)
let s = fs.readFileSync(P, 'utf8')
const before = s
const done = []

function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error('anchor "' + name + '" matched ' + n + ' times')
  s = s.replace(from, to)
  done.push(name)
}

rep('cfg-strip',
  '  slimSystem: true,',
  '  slimSystem: true,' + NL + "  stripToolHints: ['kitty'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）")

rep('ctor-strip',
  '      slimSystem: cfg.slimSystem,',
  '      slimSystem: cfg.slimSystem,' + NL + '      stripToolHints: cfg.stripToolHints,')

// 在 for 循环内、system 分支之后插入
rep('stream-strip',
  "        if (m.role === 'system' && this.profile.slimSystem !== false) {" + NL +
  '          m.content = dedupeSystem(m.content)' + NL +
  '        }' + NL +
  '      }',
  "        if (m.role === 'system' && this.profile.slimSystem !== false) {" + NL +
  '          m.content = dedupeSystem(m.content)' + NL +
  '        }' + NL +
  '        if (Array.isArray(this.profile.stripToolHints) && this.profile.stripToolHints.length) {' + NL +
  '          m.content = stripToolHints(m.content, this.profile.stripToolHints)' + NL +
  '        }' + NL +
  '      }')

// 实现函数（放在 toOpenAITools 之前）
const impl = [
  'function stripToolHints(system, tags) {',
  '  let out = String(system)',
  '  for (const tag of tags || []) {',
  '    // a) [tag-reverse:xxx ...] ... [/tag-reverse:xxx] 整块删除',
  '    const re = new RegExp(' + JSON.stringify(BS + '[' + BS + '\\]') + '.source) ',  // 占位，下面替换
].join(NL)

// 用简单可靠的字符串扫描，不用正则构造，避免转义问题
const impl2 = [
  'function stripToolHints(system, tags) {',
  '  let out = String(system)',
  '  for (const tag of tags || []) {',
  '    // a) [tag-reverse:xxx ...] ... [/tag-reverse:xxx] 整块删除',
  '    const openTag = String.fromCharCode(91) + tag + "-reverse:"',
  '    const closeTag = String.fromCharCode(91) + "/" + tag + "-reverse:"',
  '    let guard = 0',
  '    while (guard++ < 8) {',
  '      const a = out.indexOf(openTag)',
  '      if (a < 0) break',
  '      const b = out.indexOf(String.fromCharCode(93), a)',
  '      const c = b < 0 ? -1 : out.indexOf(closeTag, b)',
  '      if (c < 0) break',
  '      const d = out.indexOf(String.fromCharCode(93), c)',
  '      if (d < 0) break',
  '      out = out.slice(0, a) + out.slice(d + 1)',
  '    }',
  '    // b) kitty 的 A 通道速查段：从定位行起到 API-FREEZE 行尾',
  '    if (tag === "kitty") {',
  '      const head = out.indexOf("A 通道（KittyCE 文件桥")',
  '      if (head >= 0) {',
  '        const end = out.indexOf("API-FREEZE.md" + String.fromCharCode(96), head)',
  '        if (end > head) out = out.slice(0, head) + out.slice(end + 16)',
  '      }',
  '    }',
  '  }',
  '  return out',
  '}',
].join(NL)

rep('impl-strip', 'function toOpenAITools(tools) {', impl2 + NL + NL + 'function toOpenAITools(tools) {')

fs.writeFileSync(P + '.bak-think9', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
