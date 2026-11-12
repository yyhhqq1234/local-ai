// src/engine.ts 镜像：engineExe / engineInfo / stop 精准杀
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/plugins/dsh-ninfer-local/src/engine.ts'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

rep('iface engineExe',
`  kind: 'launcher' | 'exe'`,
`  kind: 'launcher' | 'exe'
  /** 该档位真实引擎可执行（27B 与 9B 进程同名 ninfer-serve.exe，只能靠路径区分） */
  engineExe?: string`)

rep('csunx engineExe',
`    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx',
    modelDirs: [`,
`    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx',
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx/runtime/engine/ninfer-serve.exe',
    modelDirs: [`)

rep('9b engineExe',
`    exe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps',`,
`    exe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps',`)

rep('engineInfo',
`  // ---------- 进程 ----------
  async status(): Promise<EngineState> {`,
`  // ---------- 引擎身份 ----------
  engineInfo(): { profile: string; label: string; kind: string; exe: string; exists: boolean; bytes?: number; modelDirs: string[] } {
    const params = this.readParams()
    const prof = this.profileOf(params.profile)
    const exe = prof.engineExe ?? prof.exe ?? ''
    let bytes: number | undefined
    try { bytes = statSync(exe).size } catch { bytes = undefined }
    return {
      profile: params.profile,
      label: prof.label,
      kind: prof.kind,
      exe,
      exists: bytes !== undefined,
      bytes,
      modelDirs: prof.modelDirs,
    }
  }

  // ---------- 进程 ----------
  async status(): Promise<EngineState> {`)

rep('status engine',
`      profile: params.profile,
      profiles: Object.fromEntries(Object.entries(ENGINE_PROFILES).map(([k, v]) => [k, v.label])),`,
`      profile: params.profile,
      profiles: Object.fromEntries(Object.entries(ENGINE_PROFILES).map(([k, v]) => [k, v.label])),
      engine: this.engineInfo(),`)

rep('stop safe',
`    // 兜底：按镜像名杀（本插件独占的引擎实例）
    spawn('taskkill', ['/F', '/IM', 'ninfer-serve.exe'], { windowsHide: true, stdio: 'ignore' })`,
`    // 兜底：只杀「可执行路径 == 本档位引擎」的进程。
    // 绝不能用 taskkill /IM ninfer-serve.exe —— 27B 与 9B 进程名完全相同，会误杀另一个引擎。
    const info = this.engineInfo()
    if (info.exe) {
      const esc = info.exe.replace(/'/g, "''")
      const ps = "Get-Process -Name ninfer-serve -ErrorAction SilentlyContinue | " +
        "Where-Object { $_.Path -and $_.Path.ToLower() -eq '" + esc.toLowerCase() + "' } | " +
        "ForEach-Object { Stop-Process -Id $_.Id -Force }"
      spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps], { windowsHide: true, stdio: 'ignore' })
    }`)

fs.writeFileSync(P, s, 'utf8')
console.log('src/engine.ts synced: ' + hits.join(', '))
