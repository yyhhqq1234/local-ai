// 临时自检工具注入 / 移除：验证 core ctx.llm.imageRequestPricing 调用链
// node patch-pricing-selftest.mjs add|remove
import { readFileSync, writeFileSync } from 'node:fs'

const LIB = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const mode = process.argv[2] || 'add'
let src = readFileSync(LIB, 'utf8')

const MARK_START = '  // [TEMP-PRICING-PROBE-START]'
const MARK_END = '  // [TEMP-PRICING-PROBE-END]'
const block = `${MARK_START}
  ctx.effect(() => ctx.tools.register(tool({
    name: 'ninfer_pricing_selftest',
    description: '[临时] 验证 core imageRequestPricing 调用链：ctx.llm.imageRequestPricing(provider, model)',
    parameters: { model: { type: 'string', description: '模型 id（缺省取活跃模型文件）' } },
    output: OUT,
    async execute(args) {
      const provider = cfg.provider
      const model = (args && args.model) || manager.activeModelFile() || 'local'
      const a = ctx.llm.adapters && typeof ctx.llm.adapters.get === 'function'
        ? ctx.llm.adapters.get(provider)?.adapter
        : undefined
      const out = {
        provider,
        model,
        adapterClass: a ? a.constructor.name : null,
        hasPricing: typeof (a && a.imageRequestPricing) === 'function',
        hasTarget: typeof (a && a.imageRequestTarget) === 'function',
      }
      try {
        const pricing = ctx.llm.imageRequestPricing(provider, model)
        out.serviceReturned = pricing === undefined || pricing === null ? String(pricing) : Object.keys(pricing)
        const blk = {
          type: 'image',
          attachment: {
            attachmentId: 'sha256:f2f70fa662b68beec8d3c69444a7839c8a4d1ca4ad2b553d1cdb8421aae3e879',
            width: 1441, height: 364, mediaType: 'image/png',
          },
        }
        out.prices = pricing && typeof pricing.priceImages === 'function' ? pricing.priceImages([blk]) : null
        out.target = a && typeof a.imageRequestTarget === 'function'
          ? a.imageRequestTarget(provider, model, blk.attachment)
          : null
      } catch (e) {
        out.error = String((e && e.message) || e)
      }
      return txt(out)
    },
  })), 'dsh-ninfer-local: ninfer_pricing_selftest (temp)')
${MARK_END}
`

if (mode === 'add') {
  if (src.includes(MARK_START)) { console.log('ALREADY-PRESENT'); process.exit(0) }
  const anchor = "  // 1.5) 管理面板 API"
  if (!src.includes(anchor)) { console.error('ANCHOR-MISS: 1.5 marker'); process.exit(2) }
  src = src.replace(anchor, block + '\n' + anchor)
  writeFileSync(LIB, src, 'utf8')
  console.log('ADDED')
} else if (mode === 'remove') {
  const re = new RegExp(`\\n?${MARK_START.replace(/[[\]]/g, '\\$&')}[\\s\\S]*?${MARK_END.replace(/[[\]]/g, '\\$&')}\\n?`)
  if (!re.test(src)) { console.log('NOT-PRESENT'); process.exit(0) }
  src = src.replace(re, '\n')
  writeFileSync(LIB, src, 'utf8')
  console.log('REMOVED')
} else {
  console.error('usage: node patch-pricing-selftest.mjs add|remove')
  process.exit(2)
}
