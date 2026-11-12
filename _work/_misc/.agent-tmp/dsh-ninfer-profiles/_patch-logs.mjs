// 面板日志取"最近修改"的那个文件（原来按文件名排序，会显示 10-23 的旧失败日志）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const from = `    const files = readdirSync(dir).filter((f) => f.endsWith('.log')).sort()
    const last = files[files.length - 1]
    if (!last) return []`
const to = `    const files = readdirSync(dir).filter((f) => f.endsWith('.log'))
      .map((f) => { const p = join(dir, f); let t = 0; try { t = statSync(p).mtimeMs } catch { /* ignore */ } return { f, t } })
      .sort((a, b) => a.t - b.t)
    const last = files.length ? files[files.length - 1].f : undefined
    if (!last) return []`
const n = s.split(from).length - 1
if (n !== 1) throw new Error('tailLogs anchor count=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('tailLogs: 改为按 mtime 取最新')
