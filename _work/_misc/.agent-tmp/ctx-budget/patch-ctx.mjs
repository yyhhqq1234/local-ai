// 9B 上下文策略：maxContext 16384（实测安全值）+ prompt 预算裁剪 + 输出上限
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

// 1) 档位：maxContext 4096 → 16384，并带上下文预算
rep('profile ctx',
`    defaultModel: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer',
    maxContext: 4096,`,
`    defaultModel: 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer',
    // 实测（2026-11-09，12GB 卡）：4096 装不下 DSH 的 system prompt（实测 54K 字符）；
    // 16384 → KV 256 pages / runtime 626 MiB / ready 8s / 剩余显存 2.76 GiB  ✅
    // 32768 → free 0 B、启动 1m58s、主机内存被撑满（会爆内存）  ❌
    // 65536 → FATAL Device budget cannot hold model weights
    maxContext: 16384,
    contextBudget: { window: 16384, maxOutput: 2048, reserve: 512 },`)

// 2) 裁剪：按字符估算 token，保留 system + 最近消息
rep('trim helper',
`export class NinferAdapter {`,
`/** 粗估 token：中文≈1 字/token，英文≈4 字/token，混合取 1.7 字/token（偏保守） */
function estimateTokens(text) {
  const n = typeof text === 'string' ? text.length : 0
  return Math.ceil(n / 1.7)
}

/**
 * 把 messages 裁到预算内：system 全保留，其余从最新往回填。
 * 超预算时丢弃最旧的对话消息（并插入一条说明，避免模型困惑）。
 */
function trimToBudget(messages, budgetTokens) {
  let used = 0
  for (const m of messages) used += estimateTokens(typeof m.content === 'string' ? m.content : '')
  if (used <= budgetTokens) return { messages, dropped: 0 }
  const sys = messages.filter((m) => m.role === 'system')
  const rest = messages.filter((m) => m.role !== 'system')
  let sysTokens = 0
  for (const m of sys) sysTokens += estimateTokens(typeof m.content === 'string' ? m.content : '')
  let room = budgetTokens - sysTokens
  const keep = []
  for (let i = rest.length - 1; i >= 0; i--) {
    const t = estimateTokens(typeof rest[i].content === 'string' ? rest[i].content : '')
    if (t > room) break
    room -= t
    keep.unshift(rest[i])
  }
  const dropped = rest.length - keep.length
  const head = dropped > 0
    ? [{
        role: 'system',
        content: '[上下文裁剪] 本会话较早的 ' + dropped + ' 条消息超出本地引擎上下文预算（' +
          budgetTokens + ' tokens），已被丢弃；如需该部分内容请重新提供。',
      }]
    : []
  return { messages: [...sys, ...head, ...keep], dropped }
}

export class NinferAdapter {`)

// 3) stream()：先裁剪，再算 max_tokens
rep('apply budget',
`    if (typeof this.profile.ensureModel === 'function') {`,
`    // 本地引擎上下文预算：先裁历史，再压输出长度，避免 context_length_exceeded
    const budget = this.profile.contextBudget
    if (budget && budget.window) {
      const maxOut = Math.min(Number(options.maxTokens) || budget.maxOutput, budget.maxOutput)
      this._maxOutCap = maxOut
      const promptBudget = budget.window - maxOut - (budget.reserve ?? 0)
      const trimmed = trimToBudget(messages, promptBudget)
      if (trimmed.dropped > 0) {
        messages.length = 0
        for (const m of trimmed.messages) messages.push(m)
        console.error('[dsh-ninfer-local] 裁剪历史 ' + trimmed.dropped + ' 条（预算 ' + promptBudget + ' tokens）')
      }
    }

    if (typeof this.profile.ensureModel === 'function') {`)

// 4) max_tokens 用上限
rep('max tokens cap',
`    const baseMax = Number(options.maxTokens) || 8192
    body.max_tokens = longAskRe.test(lastUserText) ? Math.max(baseMax, 16384) : baseMax`,
`    const baseMax = Number(options.maxTokens) || 8192
    const cappedMax = this._maxOutCap ? Math.min(baseMax, this._maxOutCap) : baseMax
    body.max_tokens = longAskRe.test(lastUserText) ? Math.max(cappedMax, 16384) : cappedMax`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
