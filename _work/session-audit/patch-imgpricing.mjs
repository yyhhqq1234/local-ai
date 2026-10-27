// 补 NinferAdapter.imageRequestPricing + 修 imageRequestTarget 签名
// 用法: node patch-imgpricing.mjs [--check-only]
import { readFileSync, writeFileSync } from 'node:fs'

const LIB = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/lib/index.js'
const checkOnly = process.argv.includes('--check-only')
let src = readFileSync(LIB, 'utf8')
const before = src.length
const applied = []
const failed = []

function must(name, re, repl) {
  if (!re.test(src)) { failed.push(name); return }
  src = src.replace(re, repl)
  applied.push(name)
}

// 1) 单一真相源：占位文本常量 + 纯文本图片占位/定价辅助
must('insert-helpers',
  /\/\/ ─+ 消息转换 ─+\r?\nfunction blocksToText\(blocks\) \{/,
  `// 图片在 ninfer 路由上的唯一占位文本（blocksToText 与 imageRequestPricing 共用）
const IMAGE_PLACEHOLDER_TEXT = '[图片：本机视觉为 CPU 路径，历史图片不回灌]'

// 与 core textOnlyImageText 同构：text-only 路由在出网前把 image 块替换成该文本
function imageAttachmentId(block) {
  const ref = (block && (block.attachment ?? block)) || {}
  const raw = String(ref.attachmentId ?? ref.sha256 ?? ref.id ?? '')
  return raw.startsWith('sha256:') ? raw.slice(7) : raw
}

function textOnlyImageText(block) {
  const short = imageAttachmentId(block).slice(0, 8)
  return '[image omitted because this model accepts text only; attachment sha256:' + short + ']'
}

// ───────────────────────── 消息转换 ─────────────────────────
function blocksToText(blocks) {`)

// 2) blocksToText 复用常量
must('image-case-constant',
  /case 'image': out\.push\('\[图片：本机视觉为 CPU 路径，历史图片不回灌\]'\); break/,
  `case 'image': out.push(IMAGE_PLACEHOLDER_TEXT); break`)

// 3) 适配器：补 imageRequestPricing，修 imageRequestTarget 形参
must('adapter-methods',
  /  imageRequestTarget\(image\) \{\r?\n    return \{ width: image\.width, height: image\.height, maxBytes: 4 \* 1024 \* 1024 \}\r?\n  \}/,
  `  // core 调用形态是 (provider, model, image)；保留旧形态 (image) 兼容
  imageRequestTarget(providerOrImage, modelOrImage, maybeImage) {
    const image = maybeImage
      ?? (modelOrImage && typeof modelOrImage === 'object' ? modelOrImage : undefined)
      ?? (providerOrImage && typeof providerOrImage === 'object' ? providerOrImage : {})
    const w = Math.trunc(Number(image.width))
    const h = Math.trunc(Number(image.height))
    return {
      width: w > 0 ? w : 1024,
      height: h > 0 ? h : 1024,
      maxBytes: 4 * 1024 * 1024,
      mediaType: image.mediaType,
    }
  }

  /**
   * 请求图片定价。core LlmService.imageRequestPricing(provider, model) 同步取用：
   *   this.adapters.get(provider)?.adapter.imageRequestPricing(provider, model)
   * 缺此方法 → TypeError（compact / token meter 直接失败）。
   *
   * ninfer 路由的 resolveModel 不声明 inputModalities=image，core 按纯文本路由处理，
   * 出网前已把每个 image 块替换为 textOnlyImageText；本适配器 blocksToText 再兜一层占位。
   * 故：每次出现按占位文本计价，visualTokens 恒为 0（引擎无视觉 token 预算）。
   */
  imageRequestPricing() {
    const visionCapable = this.profile?.visionCapable === true
    return {
      priceImages: (images) => (Array.isArray(images) ? images : []).map((block) => ({
        visualTokens: 0,
        text: visionCapable ? IMAGE_PLACEHOLDER_TEXT : textOnlyImageText(block),
      })),
    }
  }`)

if (failed.length) {
  console.error('ANCHOR-MISS:', failed.join(', '))
  process.exit(2)
}

if (checkOnly) {
  console.log('OK-CHECK anchors:', applied.join(', '), 'delta:', src.length - before)
  process.exit(0)
}

writeFileSync(LIB, src, 'utf8')
console.log('PATCHED:', applied.join(', '), '| bytes', before, '->', src.length)
