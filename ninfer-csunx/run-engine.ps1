# NInfer 引擎启动器（CSUNX233 v0.1.3 配方 · 5070 Ti Laptop 12GB）
# 参数全部可由 dsh-ninfer-local 插件传入；手工运行等价于插件默认值。
param(
    [int]$DeviceKV      = 36864,
    [int]$SinkTokens    = 12288,
    [int]$RecentTokens  = 19456,
    [int]$RetrieveTokens= 3840,
    [int]$HostKVMiB     = 7168,
    [string]$KVDType    = 'nvfp4',
    [int]$PrefillChunk  = 128,
    [int]$DraftTokens   = 3,
    [string]$ReasoningEffort = 'high',
    [int]$MaxContext    = 262144,
    [int]$EnginePort    = 1234,
    [string]$ModelFile  = '',
    [switch]$VisionCpu,
    [switch]$NoVision
)

$ErrorActionPreference = 'Stop'
$Root    = $PSScriptRoot
$Engine  = Join-Path $Root 'runtime\engine\ninfer-serve.exe'
$Tpl     = Join-Path $Root 'chat_template_qwen3.8-enhanced.jinja'
$ModelDir= Join-Path $Root '..\ninfer-27b-kv-stream-3arch-20261019\model'

if (-not (Test-Path $Engine)) { throw "engine missing: $Engine" }

# 选模型：显式 ModelFile > 本地 model\ > 上级包 model\
if ($ModelFile) {
    $c1 = Join-Path $Root ('model\' + $ModelFile)
    $c2 = Join-Path $ModelDir $ModelFile
    if (Test-Path $ModelFile) { $Model = $ModelFile }
    elseif (Test-Path $c1) { $Model = $c1 }
    elseif (Test-Path $c2) { $Model = $c2 }
    else { throw "model not found: $ModelFile" }
} else {
    $cands = @()
    $localDir = Join-Path $Root 'model'
    if (Test-Path $localDir) { $cands += Get-ChildItem $localDir -Filter *.ninfer -ErrorAction SilentlyContinue }
    if ($cands.Count -eq 0 -and (Test-Path $ModelDir)) { $cands = Get-ChildItem $ModelDir -Filter *.ninfer }
    if ($cands.Count -eq 0) { throw "no .ninfer model found (looked in $localDir and $ModelDir)" }
    $Model = ($cands | Sort-Object Name | Select-Object -First 1).FullName
}
if (-not (Test-Path $Model)) { throw "model missing: $Model" }

# --- KVMem 环境变量（CSUNX v0.1.3 引擎已支持全部 11 项）---
$env:NINFER_KVMEM_INDEX_HOST   = '1'
$env:NINFER_KV_RING            = '1'
$env:NINFER_KV_WINDOW          = [string]$RecentTokens
$env:NINFER_KV_RETRIEVE        = [string]$RetrieveTokens
$env:NINFER_KV_SINK            = [string]$SinkTokens
$env:NINFER_KV_REUSE_HOSTBACKED= '1'
$env:NINFER_HOST_PAGEABLE      = '1'
$env:NINFER_KV_LEASE_RING      = '1'
$env:NINFER_KVMEM_HARVEST_TEXT = '1'
if (-not $env:NINFER_KVMEM_INDEX_DECODE) { $env:NINFER_KVMEM_INDEX_DECODE = '1' }
if (-not $env:NINFER_KVMEM_CACHE_QUERY)  { $env:NINFER_KVMEM_CACHE_QUERY  = '1' }

$env:PATH = (Join-Path $Root 'runtime\engine') + ';' + $env:PATH

$engineArgs = @(
    $Model,
    '--model-id', 'qwen3.8-27b-ablit-swift15-iq2s',
    '--chat-template', $Tpl,
    '--max-context', [string]$MaxContext,
    '--kv-capacity', [string]$DeviceKV,
    '--max-concurrency', '1',
    '--max-shared-prefixes', '0',
    '--kv-dtype', $KVDType,
    '--host-kv-mib', [string]$HostKVMiB,
    '--cuda-graph-allowance-mib', '64',
    '--prefill-chunk', [string]$PrefillChunk,
    '--gdn-state-fp16',
    '--default-max-tokens', '0',
    '--kv-lease-growth',
    '--default-reasoning-effort', $ReasoningEffort,
    '--presence-penalty', '1.0',
    '--post-thinking-sampler', 'temp=0.7,top_p=0.95,presence=1.0',
    '--recover-invariant-failures',
    '--context-cache-policy', 'rolling',
    '--release-diverged-checkpoints',
    '--recency-eviction',
    '--device-state-slots', '0',
    '--no-webui',
    '--log-stats-interval-ms', '5000',
    '--host', '127.0.0.1',
    '--port', [string]$EnginePort
)

# MTP 投机解码（2026-10-27 补回）：引擎默认 SPECULATIVE DECODING off（--help 原文），
# 不传 --spec/--draft-tokens 时 decode 只有 34-40 tok/s；传 mtp + 3 实测 52-71 tok/s
# （10-20 22:12 / 10-24 23:18 日志：mtp accepted 46-81%，decode 52-71）。$DraftTokens=0 则不启用。
if ($DraftTokens -gt 0) { $engineArgs += @('--spec', 'mtp', '--draft-tokens', [string]$DraftTokens) }

if ($NoVision) {
} elseif ($VisionCpu) {
    $engineArgs += @('--vision', '--vision-cpu', '--vision-max-merged', '256')
} else {
    $engineArgs += @('--vision', '--vision-residency', 'overlay', '--vision-max-merged', '512')
}

$log = Join-Path $Root ('logs\engine-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
Write-Host "[ninfer] engine : $Engine"
Write-Host "[ninfer] model  : $Model"
Write-Host "[ninfer] devkv  : $DeviceKV  hostkv: $HostKVMiB MiB  kvdtype: $KVDType  chunk: $PrefillChunk  mtp: $DraftTokens"
Write-Host "[ninfer] effort : $ReasoningEffort  ctx: $MaxContext  port: $EnginePort"
Write-Host "[ninfer] log    : $log"

& $Engine @engineArgs 2>&1 | Tee-Object -FilePath $log
