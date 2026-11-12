# 5 请求验收 + attention 分段追踪（复现 verify/prefill NaN）
# 用法: & _tools/accept5.ps1 [-Port 1610] [-Reuse]

param(
    [int]$Port = 1610,
    [switch]$Reuse
)

$ErrorActionPreference = 'Continue'
$Root  = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe   = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model = Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Trace = Join-Path $Root '_tools\attn-stage.txt'
$Log   = Join-Path $Root '_tools\engine-run.log'
$Err   = Join-Path $Root '_tools\verify-error.txt'

$proc = $null
if (-not $Reuse) {
    Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
    Start-Sleep -Milliseconds 800
    Remove-Item -LiteralPath $Trace -ErrorAction SilentlyContinue
    $eargs = @($Model, '--max-context', '4096', '--greedy', '--no-cuda-graph',
               '--host-context-mib', '2048', '--port', "$Port")
    $proc = Start-Process -FilePath $Exe -ArgumentList $eargs -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')
    $ready = $false
    for ($i = 0; $i -lt 180; $i++) {
        Start-Sleep -Milliseconds 500
        if ($proc.HasExited) { break }
        try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2; $ready = $true; break } catch { }
    }
    if (-not $ready) { "ENGINE NOT READY"; exit 2 }
    "engine ready pid=$($proc.Id) (fresh)"
} else {
    "reuse existing engine on port $Port"
}

$sets = @(
    @{ name = 'p1-2+2';      prompt = 'What is 2+2?';                                                    mt = 32  },
    @{ name = 'p2-hello';    prompt = 'Say hello in Chinese.';                                           mt = 24  },
    @{ name = 'p3-gdn';      prompt = 'Explain what a gated delta network is in one sentence.';          mt = 48  },
    @{ name = 'p4-pyrev';    prompt = 'Write a Python one-liner to reverse a string.';                   mt = 64  },
    @{ name = 'p5-unittest'; prompt = 'List 3 benefits of unit testing.';                                mt = 128 }
)

$ok = 0; $fail = 0
foreach ($s in $sets) {
    $payload = @{
        model       = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
        messages    = @(@{ role = 'user'; content = $s.prompt })
        max_tokens  = $s.mt
        temperature = 0
        stream      = $false
    }
    $body = $payload | ConvertTo-Json -Depth 6 -Compress
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
            -ContentType 'application/json' -Body $body -TimeoutSec 300
        $txt = [string]$resp.choices[0].message.content
        $n = [Math]::Min(64, $txt.Length)
        "[$($s.name)] OK   $([int]$sw.Elapsed.TotalSeconds)s len=$($txt.Length) >>> $($txt.Substring(0, $n))"
        $ok++
    } catch {
        $msg = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $msg = $_.ErrorDetails.Message }
        if ($msg.Length -gt 140) { $msg = $msg.Substring(0, 140) }
        "[$($s.name)] FAIL $([int]$sw.Elapsed.TotalSeconds)s >>> $msg"
        $fail++
    }
}
"==== OK=$ok FAIL=$fail ===="

'---- attn-stage.txt: 只打印含 nan= 非零或末 24 行 ----'
if (Test-Path -LiteralPath $Trace) {
    $all = Get-Content -LiteralPath $Trace
    "lines=$($all.Count)"
    $bad = $all | Where-Object { $_ -match 'nan=(?!0\b)' }
    if ($bad) { "NAN_LINES=$($bad.Count)"; $bad | Select-Object -First 40 } else { 'no NaN in trace' }
    '---- tail 24 ----'
    $all | Select-Object -Last 24
} else { 'no trace file' }
if (Test-Path -LiteralPath $Err) { '---- verify-error.txt ----'; Get-Content -LiteralPath $Err -Tail 8 }
