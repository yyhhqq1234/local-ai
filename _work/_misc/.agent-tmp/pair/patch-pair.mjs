// 硬约束：27B 与 9B 引擎一一对应，禁止跨引擎切换/重启
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

// 1) start(): 模型必须属于当前档位的引擎目录
rep('start guard',
`    const model = this.activeModel()
    if (!model) throw new Error('no .ninfer model found (profile=' + params.profile + ')')
    const prof = this.profileOf(params.profile)`,
`    const model = this.activeModel()
    if (!model) throw new Error('no .ninfer model found (profile=' + params.profile + ')')
    const prof = this.profileOf(params.profile)
    // 硬约束：27B 与 9B 引擎一一对应，模型必须落在本档位的模型目录里
    const allowed = prof.modelDirs ?? []
    if (allowed.length && !allowed.some((d) => model.dir === d)) {
      throw new Error('模型 ' + model.file + ' 不属于档位 ' + params.profile +
        ' 的引擎（应在 ' + allowed.join(' | ') + '）')
    }`)

// 2) ensureModel：跨档模型直接拒绝，不再自动重启换引擎
rep('ensureModel hard pair',
`        const params = manager.readParams()
        const sameModel = String(params.modelFile || '') === hit.file
        const sameProfile = params.profile === hit.profile
        const st = await manager.status()
        if (sameModel && sameProfile) {
          if (!st.running) await manager.start({})
          return
        }
        manager.writeParams({ profile: hit.profile, modelFile: hit.file })
        await manager.restart({})`,
`        const params = manager.readParams()
        // 硬约束：27B 模型只能跑 27B 引擎，9B 模型只能跑 9B 引擎。
        // 走到这里说明请求的模型不属于当前档位 → 拒绝，不做跨引擎重启。
        if (hit.profile !== params.profile) {
          throw new Error('模型 ' + hit.file + ' 属于 ' + hit.profile + ' 引擎，当前档位是 ' +
            params.profile + '；请先在设置页切换档位，不跨引擎重启')
        }
        const st = await manager.status()
        if (String(params.modelFile || '') === hit.file) {
          if (!st.running) await manager.start({})
          return
        }
        manager.writeParams({ modelFile: hit.file })
        await manager.restart({})`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
