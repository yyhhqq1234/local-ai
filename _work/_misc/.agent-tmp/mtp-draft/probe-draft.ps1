$ErrorActionPreference = 'Continue'
$root  = 'D:\BaiduNetdiskDownload\Local-AI'
$exe   = 'D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build\apps\ninfer-serve.exe'
$model = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$log   = 'D:\BaiduNetdiskDownload\Local-AI\_tools\serve-mtp.log'
$err   = 'D:\BaiduNetdiskDownload\Local-AI\_tools\serve-mtp.log.err'
$port  = 1620

$env:NINFER_DUMP_IDS   = '1'
$env:NINFER_DUMP_DRAFT = '1'

Get-Process ninfer-serve -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 700
Remove-Item $log, $err -ErrorAction SilentlyContinue

foreach ($p in @($exe, $model)) { if (-not (Test-Path -LiteralPath $p)) { "MISS: $p"; exit 2 } }

$argv = @($model, '--max-context', '4096', '--greedy', '--host-context-mib', '2048', '--prefill-chunk', '128', '--no-thinking', '--no-cuda-graph', '--spec', 'mtp', '--draft-tokens', '1', '--port', "$port")

$proc = Start-Process -FilePath $exe -ArgumentList $argv -PassThru -RedirectStandardOutput $log -RedirectStandardError $err
"started pid=$($proc.Id)"

$sw = [Diagnostics.Stopwatch]::StartNew()
$ready = $false
while ($sw.Elapsed.TotalSeconds -lt 180) {
    Start-Sleep -Milliseconds 400
    if ($proc.HasExited) { break }
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -TimeoutSec 2; $ready = $true; break } catch { }
}
"ready=$ready after $([int]$sw.Elapsed.TotalSeconds)s"
if (-not $ready) {
    "--- err tail ---"; if (Test-Path $err) { Get-Content $err -Tail 12 }
    "--- out tail ---"; if (Test-Path $log) { Get-Content $log -Tail 12 }
    exit 1
}

$body = @{ model = 'local'; messages = @(@{ role = 'user'; content = '用三句话说明本地推理引擎的作用。' }); max_tokens = 32 } | ConvertTo-Json -Depth 5

Write-Output '=== request ==='
$t0 = Get-Date
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 300
    $c = $r.choices[0].message.content
    "resp: content_len={0} finish={1} wall={2:N1}s" -f $c.Length, $r.choices[0].finish_reason, ((Get-Date) - $t0).TotalSeconds
    "usage: " + ($r.usage | ConvertTo-Json -Compress)
} catch {
    "REQ FAIL: " + $_.Exception.Message
}
Start-Sleep -Milliseconds 1000

Write-Output '=== [draft] lines ==='
if (Test-Path $err) { Select-String -Path $err -Pattern 'draft' -SimpleMatch | Select-Object -First 40 -ExpandProperty Line }
Write-Output '=== token id lines ==='
if (Test-Path $err) { Select-String -Path $err -Pattern 'token=' -SimpleMatch | Select-Object -First 40 -ExpandProperty Line }
Write-Output '=== stats lines ==='
if (Test-Path $log) { Select-String -Path $log -Pattern 'drafted|accepted|speculative|decode ' | Select-Object -First 20 -ExpandProperty Line }
