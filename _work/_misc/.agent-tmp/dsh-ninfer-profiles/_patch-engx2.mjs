// 双引擎区分加固：stop() 不按镜像名全杀（27B 与 9B 同名 ninfer-serve.exe）；status() 暴露引擎身份
import fs from 'node:fs'
const P = 'lib/index.js'
let s = fs.readFileSync(P, 'utf8')
const hits = []
function rep(name, from, to) {
  const n = s.split(from).length - 1
  if (n !== 1) throw new Error(`[${name}] expected 1 got ${n}`)
  s = s.replace(from, () => to)
  hits.push(name)
}

// 1) 档位表补 engineExe（launcher 档位的真实可执行，用于身份识别与精准 kill）
rep('profiles engineExe',
`    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx',
    modelDirs: [`,
`    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx',
    // 27B 引擎真实可执行（run-engine.ps1 内部 $Engine）；与 9B 的 exe 同名，必须按路径区分
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx/runtime/engine/ninfer-serve.exe',
    modelDirs: [`)

rep('profiles 9b engineExe',
`    exe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps',`,
`    exe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineExe: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps/ninfer-serve.exe',
    engineDir: 'D:/BaiduNetdiskDownload/Local-AI/_tools/ninfer-build/apps',`)

// 2) 新增 engineInfo()：当前档位的引擎身份
rep('engineInfo',
`  async status() {`,
`  // ---------- 引擎身份 ----------
  /** 当前档位的引擎可执行身份（27B 与 9B 的进程名同为 ninfer-serve.exe，只能靠路径区分） */
  engineInfo() {
    const params = this.readParams()
    const prof = this.profileOf(params.profile)
    const exe = prof.engineExe ?? prof.exe ?? ''
    let bytes
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

  async status() {`)

// 3) status 暴露引擎身份
rep('status engine',
`      profile: params.profile,
      profiles: Object.fromEntries(Object.entries(ENGINE_PROFILES).map(([k, v]) => [k, v.label])),`,
`      profile: params.profile,
      profiles: Object.fromEntries(Object.entries(ENGINE_PROFILES).map(([k, v]) => [k, v.label])),
      engine: this.engineInfo(),`)

// 4) stop()：禁止按镜像名全杀
rep('stop-safe',
`  async stop() {
    try {
      const pid = readFileSync(this.pidPath, 'utf8').trim()
      if (pid) spawn('taskkill', ['/F', '/T', '/PID', pid], { windowsHide: true, stdio: 'ignore' })
    } catch { /* no pid */ }
    spawn('taskkill', ['/F', '/IM', 'ninfer-serve.exe'], { windowsHide: true, stdio: 'ignore' })
    try { rmSync(this.pidPath) } catch { /* ignore */ }`,
`  async stop() {
    const info = this.engineInfo()
    // 1) 精确按 pid（pid 文件由本档位启动时写入）
    try {
      const pid = readFileSync(this.pidPath, 'utf8').trim()
      if (pid) spawn('taskkill', ['/F', '/T', '/PID', pid], { windowsHide: true, stdio: 'ignore' })
    } catch { /* no pid */ }
    // 2) 兜底：只杀"可执行路径 == 本档位引擎"的进程。
    //    绝不能用 taskkill /IM ninfer-serve.exe —— 27B 与 9B 的进程名完全相同，会误杀另一个引擎。
    if (info.exe) {
      const esc = info.exe.replace(/'/g, "''")
      const ps = "Get-Process -Name ninfer-serve -ErrorAction SilentlyContinue | " +
        "Where-Object { $_.Path -and $_.Path.ToLower() -eq '" + esc.toLowerCase() + "' } | " +
        "ForEach-Object { Stop-Process -Id $_.Id -Force }"
      spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', ps],
        { windowsHide: true, stdio: 'ignore' })
    }
    try { rmSync(this.pidPath) } catch { /* ignore */ }`)

fs.writeFileSync(P, s, 'utf8')
console.log('patched: ' + hits.join(', '))
console.log('bytes=' + s.length)
