import fs from 'node:fs'
const s = fs.readFileSync('lib/index.js', 'utf8')
const probes = [
  'const params = { ...this.readParams(), ...overrides }',
  'const modelFile = this.activeModelFile()',
  "const script = join(this.dir, 'run-engine.ps1')",
  "if (params.vision === 'off') args.push('-NoVision')",
  'await ready // 拉起失败（ENOENT 等）在这里显式抛出，不再等满 150s，也不打穿宿主',
  'const { child, exe, ready } = spawnEngine(args, this.dir, join(this.dir, \'logs\'))',
]
for (const p of probes) {
  const n = s.split(p).length - 1
  console.log(n, '|', JSON.stringify(p.slice(0, 60)))
}
