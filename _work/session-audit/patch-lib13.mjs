// 零损提速 v2：剥离"工具不在白名单"的说明段（js-reverse MCP、Background jobs）
// 这些工具模型拿不到，留着只是噪声；删掉不影响任何可用能力
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s

// 在 stripToolHints 内部追加：按“标题起点 → 下一个标题”删除整节
const FROM = [
  '    if (tag === "kitty") {',
  '      const head = out.indexOf("A 通道（KittyCE 文件桥")',
  '      if (head >= 0) {',
  '        const end = out.indexOf("API-FREEZE.md" + String.fromCharCode(96), head)',
  '        if (end > head) out = out.slice(0, head) + out.slice(end + 16)',
  '      }',
  '    }',
].join(NL)

const TO = [
  '    if (tag === "kitty") {',
  '      const head = out.indexOf("A 通道（KittyCE 文件桥")',
  '      if (head >= 0) {',
  '        const end = out.indexOf("API-FREEZE.md" + String.fromCharCode(96), head)',
  '        if (end > head) out = out.slice(0, head) + out.slice(end + 16)',
  '      }',
  '    }',
  '    // 通用：按标题起点删到下一个同级或更高级标题',
  '    const dropSection = (startMark) => {',
  '      const a = out.indexOf(startMark)',
  '      if (a < 0) return',
  '      const rest = out.slice(a + startMark.length)',
  '      const m = rest.match(/\\n#{1,3} /)',
  '      const b = m ? a + startMark.length + m.index : out.length',
  '      out = out.slice(0, a) + out.slice(b)',
  '    }',
  '    if (tag === "js-reverse") dropSection("### MCP server: js-reverse")',
  '    if (tag === "jobs") dropSection("# Background task tools")',
].join(NL)

if (s.split(FROM).length - 1 !== 1) throw new Error('anchor for kitty block not unique')
s = s.replace(FROM, TO)

// 默认标签扩容
s = s.replace(
  "stripToolHints: ['kitty'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）",
  "stripToolHints: ['kitty', 'js-reverse', 'jobs'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）")

fs.writeFileSync(P + '.bak-think13', before)
fs.writeFileSync(P, s)
console.log('patched strip hints + defaults | delta bytes', s.length - before.length)
