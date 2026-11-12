# seq-test.ps1 — 干净引擎上按顺序打请求，判定"跨请求状态污染" vs "请求本身触发退化"
# 用法: & _work/ninfer-9b/seq-test.ps1
param([int]$Port = 1631)

$Root  = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe   = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model = Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Log   = Join-Path $Root '_work\ninfer-9b\seq-engine.log'

Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 900

$eargs = @($Model,'--max-context','4096','--greedy','--host-context-mib','2048',
           '--prefill-chunk','128','--no-thinking','--port',"$Port")
$proc = Start-Process -FilePath $Exe -ArgumentList $eargs -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')
$ready = $false
for ($i=0; $i -lt 180; $i++) {
    Start-Sleep -Milliseconds 500
    if ($proc.HasExited) { break }
    try { $null = Invoke-RestMethod "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2; $ready=$true; break } catch {}
}
if (-not $ready) { "ENGINE NOT READY"; exit 2 }
$mid = (Invoke-RestMethod "http://127.0.0.1:$Port/v1/models").data[0].id
"engine ready pid=$($proc.Id) model=$mid"

function Chat([string]$label, $msgs, [int]$mt) {
    $b = @{ model=$mid; messages=$msgs; max_tokens=$mt; temperature=0; stream=$false } | ConvertTo-Json -Depth 8 -Compress
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-RestMethod "http://127.0.0.1:$Port/v1/chat/completions" -Method Post `
             -ContentType 'application/json' -Body $b -TimeoutSec 300
    } catch { "  [$label] ERROR $($_.Exception.Message)"; return }
    $sw.Stop()
    $t = [string]$r.choices[0].message.content
    $tok = if ($r.usage.completion_tokens) { [int]$r.usage.completion_tokens } else { 0 }
    $s = [math]::Round($sw.Elapsed.TotalSeconds,2)
    $tps = if ($s -gt 0) { [math]::Round($tok/$s,1) } else { 0 }
    $head = ($t -replace "\s+",' ')
    if ($head.Length -gt 100) { $head = $head.Substring(0,100) }
    "  [$label] tok=$tok s=$s tok/s=$tps chars=$($t.Length)"
    "     >>> $head"
}

"== 1 essay alone (fresh engine) =="
Chat 'essay' @(@{role='user';content='Write a 300-word essay about why local inference matters.'}) 256

"== 2 system+user (after essay) =="
Chat 'sys' @(@{role='system';content='You are 石井, a terse assistant.'},@{role='user';content='What is 2+2?'}) 48

"== 3 user only (after sys) =="
Chat 'user' @(@{role='user';content='What is 2+2?'}) 48

"== 4 essay again (after sys request) =="
Chat 'essay2' @(@{role='user';content='Write a 300-word essay about why local inference matters.'}) 256

"---- engine alive: $(if (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue) {'yes'} else {'no'}) ----"
