# 冷启首字时延 + OpenAI 兼容面（含 tools 字段）实测
# 用法: & _tools/probe_dsh.ps1 [-Port 1670]

param([int]$Port = 1670)

$ErrorActionPreference = 'Continue'
$Root  = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe   = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model = Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Log   = Join-Path $Root '_tools\dsh-engine.log'

Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 800

$t0 = [System.Diagnostics.Stopwatch]::StartNew()
$proc = Start-Process -FilePath $Exe -ArgumentList @($Model,'--max-context','4096','--greedy',
    '--host-context-mib','2048','--port',"$Port") -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')
$ready = $false
while ($t0.Elapsed.TotalSeconds -lt 120) {
    Start-Sleep -Milliseconds 200
    if ($proc.HasExited) { break }
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2; $ready = $true; break } catch { }
}
$readyMs = [int]$t0.Elapsed.TotalMilliseconds
"engine_ready=$ready  startup_ms=$readyMs"
if (-not $ready) { Get-Content -LiteralPath ($Log + '.err') -Tail 6; exit 2 }

# 冷启后第一个请求：测 TTFT（流式读第一块）
$body = @{
    model    = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
    stream   = $true
    messages = @(@{ role = 'user'; content = 'Reply with exactly one word: pong' })
    max_tokens = 16
} | ConvertTo-Json -Depth 6 -Compress

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$ttft = -1; $chunks = 0; $text = ''
try {
    $req  = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/v1/chat/completions")
    $req.Method = 'POST'; $req.ContentType = 'application/json'
    $bytes = [Text.Encoding]::UTF8.GetBytes($body)
    $req.ContentLength = $bytes.Length
    $s = $req.GetRequestStream(); $s.Write($bytes,0,$bytes.Length); $s.Close()
    $resp = $req.GetResponse()
    $sr = New-Object IO.StreamReader($resp.GetResponseStream())
    while (($line = $sr.ReadLine()) -ne $null) {
        if ($line -match '^data: ') {
            $payload = $line.Substring(6)
            if ($payload -eq '[DONE]') { break }
            if ($ttft -lt 0) { $ttft = [int]$sw.Elapsed.TotalMilliseconds }
            $chunks++
            try { $j = $payload | ConvertFrom-Json; $text += [string]$j.choices[0].delta.content } catch { }
        }
    }
    $sr.Close(); $resp.Close()
} catch {
    "stream FAIL: $($_.Exception.Message)"
}
"ttft_ms=$ttft  chunks=$chunks  total_ms=$([int]$sw.Elapsed.TotalMilliseconds)  text=[$text]"

# 第二请求：带 tools 的 OpenAI 形状（DSH 实际会发的形状）
$body2 = @{
    model = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
    messages = @(@{ role='user'; content='What is 1+1?' })
    tools = @(@{ type='function'; function=@{ name='noop'; description='noop'; parameters=@{ type='object'; properties=@{} } } })
    max_tokens = 8
} | ConvertTo-Json -Depth 8 -Compress
$sw2 = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $r2 = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
        -ContentType 'application/json' -Body $body2 -TimeoutSec 120
    "tools_request=OK  $([int]$sw2.Elapsed.TotalMilliseconds)ms  finish=$($r2.choices[0].finish_reason)  content=[$($r2.choices[0].message.content)]"
} catch {
    $m = $_.Exception.Message; if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $m = $_.ErrorDetails.Message }
    "tools_request=FAIL >>> $m"
}

if ($proc.HasExited) { "engine EXITED code=$($proc.ExitCode)" } else { "engine alive pid=$($proc.Id)" }
