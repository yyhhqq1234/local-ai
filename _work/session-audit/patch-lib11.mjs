// 修正环境事实：本机有 Python（Anaconda 3.13.9），PATH 里的 python 是 WindowsApps 0 字节占位符
import fs from 'node:fs'

const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const NL = String.fromCharCode(10)
let s = fs.readFileSync(P, 'utf8')
const before = s

const RULES = [
  '## 本地执行纪律（自动注入）',
  '1) 工具缺失即上报：请求的工具名不在当前可用列表时，第一条回复直接说明并请求授权；严禁去源码/目录里找替代调用路径，严禁自造桥接脚本。',
  '2) 环境事实（已实测）：PATH 里的 python / python3 是 WindowsApps 的 0 字节应用别名，执行后无输出，不代表没有 Python；真实解释器在 C:\\ProgramData\\anaconda3\\python.exe（Python 3.13.9），必须用全路径调用；py 启动器不存在；node 可用；shell 统一用 pwsh 工具，不要用 ops_bash 套 powershell -Command。',
  '3) 验收纪律：写文件后最多回读 1 次；禁止用 wc -l / stat 反复量同一文件；达到目标即停止。',
  '4) 规格核对：任务给了字数/行数/数量要求时，交付前先核对，不足就续写，不要提前收工。',
  '5) 产物自检：落盘后按类型验一次——HTML 看标签闭合与关键元素；Python 脚本用全路径解释器跑一次（C:\\ProgramData\\anaconda3\\python.exe script.py）或至少 py_compile；跑不了必须明说原因。',
  '6) 临时文件放 _tmp/，任务结束删掉，不在工作区留垃圾。',
].join(NL)

const lines = s.split(NL)
const idx = lines.findIndex((l) => l.startsWith('  executionRules: '))
if (idx < 0) throw new Error('executionRules line not found')
const oldLen = lines[idx].length
lines[idx] = '  executionRules: ' + JSON.stringify(RULES) + ','
const out = lines.join(NL)

fs.writeFileSync(P + '.bak-think11', before)
fs.writeFileSync(P, out)
console.log('patched executionRules: line', idx + 1, 'oldLen', oldLen, 'newLen', lines[idx].length)
