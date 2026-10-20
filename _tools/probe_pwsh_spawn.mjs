// 探针：复刻插件的 spawn 语义，找出 pwsh 秒退 code=0 的原因
import { spawn } from 'node:child_process'
import { openSync, closeSync, writeFileSync, readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

const DIR = 'D:\\BaiduNetdiskDownload\\Local-AI\\ninfer-csunx'
const script = join(DIR, 'run-engine.ps1')
const args = [
  '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script,
  '-DeviceKV', '36864', '-HostKVMiB', '7168', '-KVDType', 'nvfp4',
  '-PrefillChunk', '128', '-DraftTokens', '3', '-ReasoningEffort', 'high',
  '-MaxContext', '262144', '-EnginePort', '1235', '-ModelFile',
  'Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer', '-VisionCpu',
]
const exeCands = [
  'C:\\Program Files\\PowerShell\\7\\pwsh.exe',
  'C:\\Program Files (x86)\\PowerShell\\7\\pwsh.exe',
]
const exe = exeCands.find((p) => existsSync(p))
console.log('exe =', exe)
console.log('env ProgramFiles =', process.env.ProgramFiles, '| x86 =', process.env['ProgramFiles(x86)'])

const mode = process.argv[2] ?? 'a'

function run(name, opts) {
  return new Promise((res) => {
    const t0 = Date.now()
    const child = spawn(exe, args, opts)
    let out = ''
    child.stdout?.on('data', (d) => (out += d))
    child.stderr?.on('data', (d) => (out += d))
    child.on('error', (e) => res({ name, err: String(e && e.message) }))
    child.on('exit', (code, sig) =>
      res({ name, code, sig, ms: Date.now() - t0, out: out.slice(0, 1200) }))
    setTimeout(() => { try { child.kill() } catch {} }, 8000)
  })
}

const log = join(DIR, 'logs', 'probe-launcher.log')
const fd = openSync(log, 'a')

const variants = {
  a: { name: 'detached+ignore', opts: { cwd: DIR, windowsHide: true, stdio: 'ignore', detached: true } },
  b: { name: 'detached+fd', opts: { cwd: DIR, windowsHide: true, stdio: ['ignore', fd, fd], detached: true } },
  c: { name: 'pipe(no detach)', opts: { cwd: DIR, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] } },
  d: { name: 'inherit(no detach)', opts: { cwd: DIR, windowsHide: true, stdio: ['ignore', 'inherit', 'inherit'] } },
}

const v = variants[mode]
if (!v) { console.log('modes: a b c d'); process.exit(1) }
const r = await run(v.name, v.opts)
try { closeSync(fd) } catch {}
console.log(JSON.stringify(r, null, 2))
try { console.log('--- probe-launcher.log ---\n' + readFileSync(log, 'utf8').slice(-1500)) } catch {}
process.exit(0)
