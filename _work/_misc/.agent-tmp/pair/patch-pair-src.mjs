// src/engine.ts 镜像：start() 增加"模型必须属于本档位引擎目录"的硬约束
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/src/engine.ts'
let s = fs.readFileSync(P, 'utf8')
const from = `    const model = this.activeModel()
    if (!model) throw new Error(\`no .ninfer model in profile=\${params.profile}\`)
    const prof = this.profileOf(params.profile)`
const to = `    const model = this.activeModel()
    if (!model) throw new Error(\`no .ninfer model in profile=\${params.profile}\`)
    const prof = this.profileOf(params.profile)
    // 硬约束：27B 与 9B 引擎一一对应，模型必须落在本档位的模型目录里
    const allowed = prof.modelDirs ?? []
    if (allowed.length && !allowed.includes(model.dir)) {
      throw new Error('模型 ' + model.file + ' 不属于档位 ' + params.profile +
        ' 的引擎（应在 ' + allowed.join(' | ') + '）')
    }`
const n = s.split(from).length - 1
if (n !== 1) throw new Error('anchor=' + n)
s = s.replace(from, () => to)
fs.writeFileSync(P, s, 'utf8')
console.log('src/engine.ts mirrored')
