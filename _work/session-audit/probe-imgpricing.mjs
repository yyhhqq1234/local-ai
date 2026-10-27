// 运行时探针：验证 NinferAdapter 已具备 imageRequestPricing / imageRequestTarget 契约
const M = 'file:///C:/Users/Administrator/.dsh/profiles/web/node_modules/@dsh-external/dsh-ninfer-local/lib/index.js'
const mod = await import(M)
const A = mod.NinferAdapter
if (!A) { console.error('FAIL: NinferAdapter export missing'); process.exit(1) }
const a = new A({})
const out = {}
out.hasPricing = typeof a.imageRequestPricing === 'function'
out.hasTarget = typeof a.imageRequestTarget === 'function'

const block = {
  type: 'image',
  attachment: {
    attachmentId: 'sha256:f2f70fa662b68beec8d3c69444a7839c8a4d1ca4ad2b553d1cdb8421aae3e879',
    width: 1441, height: 364, mediaType: 'image/png',
  },
}
try {
  const pricing = a.imageRequestPricing('ninfer', 'qwen3.8-27b-ablit-swift15-iq2s')
  out.pricingShape = Object.keys(pricing)
  out.prices = pricing.priceImages([block, { ...block, offloaded: true }])
} catch (e) { out.pricingError = String(e && e.message || e) }

try {
  out.targetCore = a.imageRequestTarget('ninfer', 'qwen3.8-27b-ablit-swift15-iq2s', block.attachment)
  out.targetLegacy = a.imageRequestTarget({ width: 800, height: 600 })
} catch (e) { out.targetError = String(e && e.message || e) }

console.log(JSON.stringify(out, null, 2))
const ok = out.hasPricing && out.hasTarget && !out.pricingError && !out.targetError
  && out.prices && out.prices.length === 2 && out.prices.every((p) => p.visualTokens === 0 && typeof p.text === 'string' && p.text.length > 0)
  && out.targetCore && out.targetCore.width === 1441 && out.targetLegacy.width === 800
console.log(ok ? 'VERDICT PASS' : 'VERDICT FAIL')
process.exit(ok ? 0 : 1)
