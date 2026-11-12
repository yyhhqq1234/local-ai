// shim-unit.mjs — parseTextToolCall 单元验证（9B 文本工具调用 shim）
import { parseTextToolCall } from '../../plugins/dsh-ninfer-local/lib/index.js'

const ALLOW = ['read', 'write', 'edit', 'ops_bash', 'kitty_ce', 'kitty_ops']

const cases = [
  ['marker-json',
    '先读一下：<tool_call>{"name":"read","arguments":{"path":"README.md","limit":20}}</tool_call>',
    (r) => r && r.name === 'read' && r.args.limit === 20 && r.text === '先读一下：'],
  ['fence-json',
    '```json\n{"name":"kitty_ce","arguments":{"op":"MODENUM"}}\n```',
    (r) => r && r.name === 'kitty_ce' && r.args.op === 'MODENUM'],
  ['legacy-op',
    'kitty_ce op=MODENUM\n判据：取 base 与 size。',
    (r) => r && r.name === 'kitty_ce' && r.args.op === 'MODENUM' && r.text.includes('判据')],
  ['legacy-inline',
    '先看模块：\nkitty_ce op=R|dword|0x7FF6DADB1000\n',
    (r) => r && r.args.op === 'R|dword|0x7FF6DADB1000'],
  ['denied-tool',
    '<tool_call>{"name":"rm_rf","arguments":{"path":"/"}}</tool_call>',
    (r) => r === null],
  ['plain-text',
    '本地推理有三个好处：数据不出域、低延迟、可离线。',
    (r) => r === null],
  ['bad-json',
    '<tool_call>{name: read</tool_call>',
    (r) => r === null],
  ['args-string',
    '<tool_call>{"name":"read","arguments":"{\\"path\\":\\"a.md\\"}"}</tool_call>',
    (r) => r && r.name === 'read' && r.args.path === 'a.md'],
  // 形态 3：裸 JSON 行（模型漏写标记）
  ['bare-name',
    '{"name":"read","arguments":{"path":"a.md"}}',
    (r) => r && r.name === 'read' && r.args.path === 'a.md'],
  ['bare-op-as-name',
    '{"op":"read","path":"README.md","limit":20}\n1. 项目说明',
    (r) => r && r.name === 'read' && r.args.path === 'README.md' && r.text.startsWith('1. 项目说明')],
  ['bare-json-not-a-call',
    '{"status":"ok","count":3}',
    (r) => r === null],
]

let pass = 0
for (const [name, input, check] of cases) {
  let got
  try { got = parseTextToolCall(input, ALLOW) } catch (e) { got = { __err: String(e && e.message) } }
  const ok = check(got)
  pass += ok ? 1 : 0
  console.log((ok ? 'PASS ' : 'FAIL ') + name + ' -> ' + JSON.stringify(got))
}
console.log('\n' + pass + '/' + cases.length + ' pass')
process.exit(pass === cases.length ? 0 : 1)
