// 二版：除 lib/index.js 外，再补 legacy 入口 index.js
// （DSH 自定义 resolve hook 会按包目录下 index.js 兜底，只给 exports 不够）
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const ASAR_DIR = 'C:/Users/Administrator/AppData/Local/Programs/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai'

const PLANS = [
  ['C:/Users/Administrator/.dsh/plugins/@wasd258/dsh-prompt-inject',
    ['dsh-tools', 'dsh-agent', 'dsh-system-prompt', 'dsh-scope']],
  ['C:/Users/Administrator/.dsh/plugins/dsh-commandcode-goat', ['cosmokit']],
]

for (const [plugin, pkgs] of PLANS) {
  for (const name of pkgs) {
    const src = join(ASAR_DIR, name, 'lib', 'index.js').replace(/\\/g, '/')
    const url = 'file:///' + encodeURI(src)
    const dir = join(plugin, 'node_modules', '@deepseek-ai', name)
    mkdirSync(join(dir, 'lib'), { recursive: true })

    const body = `// stub: forward to the real module inside app.asar (Electron loads asar via file://)\nexport * from '${url}'\n`
    writeFileSync(join(dir, 'lib', 'index.js'), body, 'utf8')
    writeFileSync(join(dir, 'index.js'), body, 'utf8') // legacy 入口兜底

    writeFileSync(join(dir, 'package.json'), JSON.stringify({
      name: `@deepseek-ai/${name}`,
      version: '0.0.0-asar-stub',
      private: true,
      type: 'module',
      main: './index.js',
      module: './index.js',
      exports: { '.': { default: './index.js' }, './package.json': './package.json' },
    }, null, 2) + '\n', 'utf8')
    console.log(`STUB2 ${plugin.split(/[\\/]/).pop()} -> @deepseek-ai/${name}  (index.js + lib/index.js)`)
  }
}
