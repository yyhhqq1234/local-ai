// 后端 /state 补齐档位/引擎/模型归属，供设置页消费
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

rep('state payload',
`            params: st.params,
            activeModelFile: st.modelFile,
            models: manager.listModels().map((m) => ({ file: m.file, gib: +(m.bytes / 2 ** 30).toFixed(2) })),
            logs: st.logs,`,
`            params: st.params,
            profile: st.profile,
            profiles: st.profiles,
            engine: st.engine,
            activeModelFile: st.modelFile,
            models: manager.listModels().map((m) => ({ file: m.file, gib: +(m.bytes / 2 ** 30).toFixed(2), profile: m.profile })),
            logs: st.logs,`)

// ninfer_status 也补上档位与引擎身份
rep('status tool payload',
`        params: st.params,
        activeModelFile: st.modelFile,
        modelFiles: manager.listModels().map((m) => \`\${m.file} (\${(m.bytes / 2 ** 30).toFixed(2)} GiB)\`),`,
`        params: st.params,
        profile: st.profile,
        profiles: st.profiles,
        engine: st.engine,
        activeModelFile: st.modelFile,
        modelFiles: manager.listModels().map((m) => \`\${m.profile} · \${m.file} (\${(m.bytes / 2 ** 30).toFixed(2)} GiB)\`),`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
