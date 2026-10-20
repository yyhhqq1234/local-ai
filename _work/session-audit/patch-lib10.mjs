// 追加本地模型执行纪律（工具缺失上报 / 环境事实 / 验收纪律 / 规格核对 / 产物自检 / 临时文件）
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

const RULES = [
  '## 本地执行纪律（自动注入）',
  '1) 工具缺失即上报：请求的工具名不在当前可用列表时，第一条回复直接说明并请求授权；严禁去源码/目录里找替代调用路径，严禁自造桥接脚本。',
  '2) 环境事实：本机没有 python / python3 / py；node 可用；shell 统一用 pwsh 工具，不要用 ops_bash 套 powershell -Command。',
  '3) 验收纪律：写文件后最多回读 1 次；禁止用 wc -l / stat 反复量同一文件；达到目标即停止，不做无意义的自我校验循环。',
  '4) 规格核对：任务给了字数/行数/数量要求时，交付前先核对，不足就续写，不要提前收工。',
  '5) 产物自检：落盘后按类型验一次——HTML 看标签闭合与关键元素、脚本能跑就跑一次、跑不了必须明说「本机无法运行」。',
  '6) 临时文件放 _tmp/，任务结束删掉，不在工作区留垃圾。',
].join(NL)

// 1) 配置项
rep('cfg-rules',
  "  stripToolHints: ['kitty'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）",
  "  stripToolHints: ['kitty'],   // 白名单里没有的工具，其使用说明一并剔除（消矛盾 + 省 token）" + NL +
  '  executionRules: ' + JSON.stringify(RULES) + ',')

// 2) 构造传参
rep('ctor-rules',
  '      stripToolHints: cfg.stripToolHints,',
  '      stripToolHints: cfg.stripToolHints,' + NL + '      executionRules: cfg.executionRules,')

// 3) 注入：紧跟在工具裁剪之后（body 构造之前）
rep('inject-rules',
  "    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))",
  '    if (this.profile.executionRules) {' + NL +
  '      const rules = String(this.profile.executionRules)' + NL +
  "      const sysMsg = messages.find((m) => m.role === 'system' && typeof m.content === 'string')" + NL +
  '      if (sysMsg) sysMsg.content = sysMsg.content + String.fromCharCode(10) + String.fromCharCode(10) + rules' + NL +
  "      else messages.unshift({ role: 'system', content: rules })" + NL +
  '    }' + NL +
  "    const tools = toOpenAITools(filterTools(options.tools, this.profile.toolAllowlist))")

fs.writeFileSync(P + '.bak-think10', before)
fs.writeFileSync(P, s)
console.log('patched:', done.join(', '), '| delta bytes', s.length - before.length)
