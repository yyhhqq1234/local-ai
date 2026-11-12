import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/PATCHES.md'
const BT = String.fromCharCode(96), F = BT + BT + BT
const lines = [
  '',
  '## think-engx11 · 2026-11-09 01:3x · 27B / 9B 引擎一一对应（禁止跨引擎混用）',
  '',
  '**操作者约束**：27B 与 9B 的引擎必须一一对应，不能混着用。',
  '',
  '**配对表（硬编码在档位里，代码层面校验）**',
  F,
  '27B → csunx 引擎：ninfer-csunx/runtime/engine/ninfer-serve.exe',
  '      模型目录：ninfer-csunx/model · ninfer-27b-kv-stream-3arch-20261019/model',
  '9B  → 自建引擎：_tools/ninfer-build/apps/ninfer-serve.exe',
  '      模型目录：train/lines/9b-oxcoder/out',
  F,
  '',
  '**本轮改动**',
  F,
  'lib/index.js  start()：模型必须落在本档位 modelDirs 内，否则抛错（不再"随便拿个模型喂给当前引擎"）',
  '              ensureModel()：请求的模型若属于另一个档位 → 直接拒绝并提示先切档位，',
  '                             不再自动改 profile + 重启（那等于跨引擎调度）',
  '              （stop() 已在 engx2 改为只杀本档位 exe，不会误杀另一台引擎）',
  'src/engine.ts  同步镜像 start() 的目录校验',
  F,
  '',
  '**为什么这样定**：实测两套引擎能力集不重叠，混用必失败——',
  F,
  '27B 产物 + 自建引擎 → FATAL weight/000184: unknown tensor layout: gguf_blocks_v1',
  '9B 产物 + csunx 引擎 → FATAL text/layers/0: input projection: unsupported logical projection geometry',
  F,
  '',
  '**验证**：node --check lib/index.js = 0；两处守卫静态命中（L349/L1395 附近）。',
  '',
  '**回滚**：' + BT + 'Copy-Item lib\\index.js.bak-engx11 lib\\index.js -Force' + BT,
]
fs.appendFileSync(P, lines.join('\n') + '\n', 'utf8')
console.log('PATCHES.md bytes =', fs.statSync(P).size)
