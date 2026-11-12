# decode 吞吐基准：同一 prompt 连续两次（第二次命中前缀复用，接近纯 decode）
# 用法: & _tools/bench_decode.ps1 [-Port 1640] [-Graph] [-Tokens 192] [-Runs 3]

param([int]$Port = 1640, [switch]$Graph, [int]$Tokens = 192, [int]$Runs = 3,
      [string]$Spec = '', [int]$Draft = 0)

$ErrorActionPreference = 'Continue'
$Root  = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe   = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model = Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Log   = Join-Path $Root '_tools\bench-engine.log'

Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 800

$eargs = @($Model, '--max-context', '4096', '--greedy', '--host-context-mib', '2048', '--port', "$Port")
if (-not $Graph) { $eargs += '--no-cuda-graph' }
if ($Spec) { $eargs += '--spec'; $eargs += $Spec }
if ($Draft -gt 0) { $eargs += '--draft-tokens'; $eargs += "$Draft" }
$mode = if ($Graph) { 'cuda-graph' } else { 'no-cuda-graph' }
if ($Spec) { $mode = "$mode+$Spec" + $(if($Draft -gt 0){"$Draft"}else{""}) }

$proc = Start-Process -FilePath $Exe -ArgumentList $eargs -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')
$ready = $false
for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2; $ready = $true; break } catch { }
}
if (-not $ready) {
    "MODE=$mode ENGINE NOT READY (exited=$($proc.HasExited))"
    if (Test-Path -LiteralPath $Log) { Get-Content -LiteralPath $Log -Tail 20 }
    exit 2
}
"MODE=$mode ready pid=$($proc.Id)"

$payload = @{ model = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
              messages = @(@{ role = 'user'; content = 'Explain the tradeoffs between batching and latency in GPU inference.' })
              max_tokens = $Tokens; temperature = 0; stream = $false }
$body = $payload | ConvertTo-Json -Depth 6 -Compress

$best = 0.0; $okc = 0
for ($r = 1; $r -le $Runs; $r++) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
            -ContentType 'application/json' -Body $body -TimeoutSec 600
        $sw.Stop()
        $txt = [string]$resp.choices[0].message.content
        $tok = if ($resp.usage -and $resp.usage.completion_tokens) { [int]$resp.usage.completion_tokens } else { 0 }
        $sec = $sw.Elapsed.TotalSeconds
        $tps = if ($sec -gt 0 -and $tok -gt 0) { [math]::Round($tok / $sec, 2) } else { 0 }
        if ($tps -gt $best) { $best = $tps }
        $okc++
        "[run$r] OK {$mode} tok=$tok sec=$([math]::Round($sec,2)) tok/s=$tps chars=$($txt.Length)"
    } catch {
        $sw.Stop()
        $msg = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
        if ($msg.Length -gt 120) { $msg = $msg.Substring(0, 120) }
        "[run$r] FAIL {$mode} $([math]::Round($sw.Elapsed.TotalSeconds,2))s >>> $msg"
    }
}
"==== $mode  ok=$okc/$Runs  best_tok/s=$best ===="
if ($proc.HasExited) { "engine EXITED code=$($proc.ExitCode)" } else { "engine alive pid=$($proc.Id)" }
