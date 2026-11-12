# 复现脚本：同一 prompt 连打 N 轮，抓 attention 分段 NaN 证据
# 用法: & _tools/repro-attn.ps1 [-Port 1610] [-Rounds 3] [-MaxTokens 24] [-Prompt 'What is 2+2?']

param(
    [int]$Port = 1610,
    [int]$Rounds = 3,
    [int]$MaxTokens = 24,
    [string]$Prompt = 'What is 2+2?',
    [switch]$NoPrefixReuse
)

$ErrorActionPreference = 'Continue'
$Root  = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe   = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model = Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Trace = Join-Path $Root '_tools\attn-stage.txt'
$Log   = Join-Path $Root '_tools\engine-run.log'

foreach ($p in @($Exe, $Model)) { if (-not (Test-Path -LiteralPath $p)) { "MISS $p"; exit 2 } }

Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 800
Remove-Item -LiteralPath $Trace -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Log -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ($Log + '.err') -ErrorAction SilentlyContinue

$eargs = @($Model, '--max-context', '4096', '--greedy', '--no-cuda-graph',
           '--host-context-mib', '2048', '--port', "$Port")
if ($NoPrefixReuse) { $eargs += '--no-prefix-reuse' }

"start: $Exe $($eargs -join ' ')"
$proc = Start-Process -FilePath $Exe -ArgumentList $eargs -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')

$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    try {
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2
        $ready = $true
        break
    } catch { }
}
if (-not $ready) {
    "ENGINE NOT READY (exited=$($proc.HasExited))"
    if (Test-Path -LiteralPath $Log) { '---- engine log tail ----'; Get-Content -LiteralPath $Log -Tail 25 }
    exit 2
}
"engine ready pid=$($proc.Id)"

$payload = @{
    model       = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
    messages    = @(@{ role = 'user'; content = $Prompt })
    max_tokens  = $MaxTokens
    temperature = 0
    stream      = $false
}
$body = $payload | ConvertTo-Json -Depth 6 -Compress

for ($k = 1; $k -le $Rounds; $k++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
            -ContentType 'application/json' -Body $body -TimeoutSec 300
        $txt = [string]$resp.choices[0].message.content
        $n   = [Math]::Min(72, $txt.Length)
        "[round $k] OK   $([int]$sw.Elapsed.TotalSeconds)s len=$($txt.Length) >>> $($txt.Substring(0, $n))"
    } catch {
        $msg = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
        if ($msg.Length -gt 160) { $msg = $msg.Substring(0, 160) }
        "[round $k] FAIL $([int]$sw.Elapsed.TotalSeconds)s >>> $msg"
    }
}

'---- attn-stage.txt (tail 80) ----'
if (Test-Path -LiteralPath $Trace) { Get-Content -LiteralPath $Trace -Tail 80 } else { 'no trace file' }
'---- engine alive ----'
if ($proc.HasExited) { "EXITED code=$($proc.ExitCode)" } else { "alive pid=$($proc.Id)" }
