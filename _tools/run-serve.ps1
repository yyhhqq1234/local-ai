# 启动 ninfer-serve（9B/OxCoder 当前可用配置）
# 用法：& _tools\run-serve.ps1            （默认端口 1610、后台起、日志落 _tools\serve.log）
#       & _tools\run-serve.ps1 -Port 1700 -Foreground
#
# 为什么是这两个参数（2026-11-08 实测）：
#   --prefill-chunk 128   prefill 块宽 >128 时，L03 全注意力层的 proj_k/proj_v（1024 行段）会 NaN
#                         → logits 越界 → HTTP 500 → 引擎 503。压到 128 后 312/360 token 的请求均可完成。
#   --no-thinking         不关的话输出全落进 reasoning_content，message.content 为空（长 prompt 尤其明显）。

param(
    [int]$Port = 1610,
    [string]$Model = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer',
    [int]$MaxContext= 16384,
    [int]$HostContextMiB = 2048,
    [int]$PrefillChunk = 128,
    [bool]$NoThinking = $true,
    [switch]$NoCudaGraph,
    [switch]$Foreground
)

$Root = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe  = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Log  = Join-Path $Root '_tools\serve.log'

foreach ($p in @($Exe, $Model)) { if (-not (Test-Path -LiteralPath $p)) { "MISS: $p"; exit 2 } }

Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 800

$args = @($Model, '--max-context', "$MaxContext", '--greedy',
          '--host-context-mib', "$HostContextMiB",
          '--prefill-chunk', "$PrefillChunk", '--port', "$Port")
if ($NoThinking) { $args += '--no-thinking' }
if ($NoCudaGraph) { $args += '--no-cuda-graph' }

"start: $Exe $($args -join ' ')"

if ($Foreground) {
    & $Exe @args
    exit $LASTEXITCODE
}

$proc = Start-Process -FilePath $Exe -ArgumentList $args -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')

$sw = [Diagnostics.Stopwatch]::StartNew()
$ready = $false
while ($sw.Elapsed.TotalSeconds -lt 180) {
    Start-Sleep -Milliseconds 400
    if ($proc.HasExited) { break }
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2; $ready = $true; break } catch { }
}
"ready=$ready after $([int]$sw.Elapsed.TotalSeconds)s  pid=$($proc.Id)  log=$Log"
if (-not $ready -and (Test-Path -LiteralPath ($Log + '.err'))) { Get-Content -LiteralPath ($Log + '.err') -Tail 8 }
