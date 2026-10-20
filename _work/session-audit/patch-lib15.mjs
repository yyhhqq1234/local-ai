// B 方案：把 kitty_ce / kitty_ops 两个入口加进白名单（与保留的 kitty 提示一致）
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const before = s

const OLD = "  toolAllowlist: ['write', 'read', 'edit', 'ops_bash', 'ops_glob', 'ops_grep', 'skill', 'web_search', 'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params'],"
const NEW = "  toolAllowlist: ['write', 'read', 'edit', 'ops_bash', 'ops_glob', 'ops_grep', 'skill', 'web_search', 'ninfer_status', 'ninfer_engine', 'ninfer_model', 'ninfer_params', 'kitty_ce', 'kitty_ops'],"

const n = s.split(OLD).length - 1
if (n !== 1) throw new Error('anchor matched ' + n + ' times')
s = s.replace(OLD, NEW)

fs.writeFileSync(P + '.bak-think15', before)
fs.writeFileSync(P, s)
console.log('patched toolAllowlist 12 → 14 (kitty_ce, kitty_ops) | delta bytes', s.length - before.length)
