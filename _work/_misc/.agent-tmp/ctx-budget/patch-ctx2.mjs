// 修正：contextBudget 要随"当前档位"动态取（adapter profile 是 apply() 里拼的，不是 ENGINE_PROFILES）
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

// 1) stream() 里按函数/对象两种形态取预算
rep('budget resolve',
`    const budget = this.profile.contextBudget
    if (budget && budget.window) {`,
`    const budget = typeof this.profile.contextBudget === 'function'
      ? this.profile.contextBudget()
      : this.profile.contextBudget
    if (budget && budget.window) {`)

// 2) apply() 给 adapter 传动态预算
rep('pass budget',
`      // 选择器里同时给出 27B 与 9B 全部模型，名字后缀标档位`,
`      // 上下文预算随当前档位走（9B 16384 / 27B 不设限）
      contextBudget: () => {
        try {
          const prof = ENGINE_PROFILES[manager.readParams().profile]
          return prof && prof.contextBudget ? prof.contextBudget : undefined
        } catch { return undefined }
      },
      // 选择器里同时给出 27B 与 9B 全部模型，名字后缀标档位`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
