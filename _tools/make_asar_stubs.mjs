// 为缺依赖插件补 asar 内包的 stub 转发（工作区外写：操作者已授权本次清理）
// 原理：宿主是 Electron，自身就是从 app.asar 内部以 file:// 加载 ESM 的；
// 因此在插件 node_modules 里放一个只做 `export * from 'file:///...app.asar/...'` 的壳，
// 解析与内部依赖（cosmokit/schemastery 等）都回到 asar 内的真实位置，不会二次缺失。
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const ASAR_DIR = 'C:/Users/Administrator/AppData/Local/Programs/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai'

const PLANS = [
  {
    plugin: 'C:/Users/Administrator/.dsh/plugins/@wasd258/dsh-prompt-inject',
    pkgs: ['dsh-tools', 'dsh-agent', 'dsh-system-prompt', 'dsh-scope'],
  },
  {
    plugin: 'C:/Users/Administrator/.dsh/plugins/dsh-commandcode-goat',
    pkgs: ['cosmokit'],
  },
]

const fileUrl = (p) => 'file:///' + encodeURI(p.replace(/\\/g, '/')).replace(/^file:\/\/\//, '')

let done = 0, skip = 0
for (const plan of PLANS) {
  for (const name of plan.pkgs) {
    const src = join(ASAR_DIR, name, 'lib', 'index.js').replace(/\\/g, '/')
    // asar 内文件对普通 fs 不可见，无法 existsSync 校验；直接按已知结构生成
    const dir = join(plan.plugin, 'node_modules', '@deepseek-ai', name)
    const libDir = join(dir, 'lib')
    mkdirSync(libDir, { recursive: true })

    const url = 'file:///' + encodeURI(src)
    writeFileSync(join(libDir, 'index.js'),
      `// stub: forward to the real module inside app.asar (Electron can load asar via file://)\n` +
      `export * from '${url}'\n`, 'utf8')

    writeFileSync(join(dir, 'package.json'), JSON.stringify({
      name: `@deepseek-ai/${name}`,
      version: '0.0.0-asar-stub',
      private: true,
      type: 'module',
      main: './lib/index.js',
      exports: { '.': { default: './lib/index.js' }, './package.json': './package.json' },
    }, null, 2) + '\n', 'utf8')
    console.log(`STUB  ${plan.plugin.split(/[\\/]/).pop()}  ->  @deepseek-ai/${name}`)
    done++
  }
}
console.log(`\ncreated=${done} skipped=${skip}`)
