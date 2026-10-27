# 重启本地引擎到 MTP 档并实测 decode；失败自动回退到无 MTP 启动器，保证引擎可用。
# 跑法：pwsh -NoProfile -File D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\restart-engine-mtp.ps1
$ErrorActionPreference = 'Stop'
$api   = 'http://127.0.0.1:58725/dsh-ninfer-local/api/engine'
$models= 'http://127.0.0.1:1234/v1/models'
$chat  = 'http://127.0.0.1:1234/v1/chat/completions'
$root  = 'D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx'

function Wait-Ready([int]$sec) {
    $deadline = (Get-Date).AddSeconds($sec)
    while ((Get-Date) -lt $deadline) {
        try { $r = Invoke-RestMethod -Uri $models -TimeoutSec 3; if ($r.data) { return $true } } catch { }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Restart-Engine {
    $body = @{ action = 'restart' } | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Uri $api -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 300
        return ($r | ConvertTo-Json -Compress)
    } catch {
        return "ERR: $($_.Exception.Message)"
    }
}

"== step1 带上 --spec mtp --draft-tokens 3 重启 =="
Restart-Engine
$ok = Wait-Ready 240
"ready(MTP) = $ok"

if (-not $ok) {
    "!! MTP 启动失败，回退到备份启动器（无 --spec）"
    Copy-Item "$root\run-engine.ps1.bak-nospec" "$root\run-engine.ps1" -Force
    Restart-Engine
    $ok2 = Wait-Ready 240
    "ready(FALLBACK) = $ok2"
    $log = (Get-ChildItem "$root\logs" -Filter 'engine-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
    "--- 失败日志尾部 ---"
    Get-Content $log -Tail 15
    exit 2
}

"`n== step2 实测 200 token 解码 =="
$body = @{ model='qwen3.8-27b-ablit-swift15-iq2s'; messages=@(@{role='user'; content='用一句话说明 KV cache 的作用。'}); max_tokens=200; stream=$false } | ConvertTo-Json -Depth 6
$sw = [Diagnostics.Stopwatch]::StartNew()
$r  = Invoke-RestMethod -Uri $chat -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 300
$sw.Stop()
"completion_tokens = $($r.usage.completion_tokens)  wall = $([math]::Round($sw.Elapsed.TotalSeconds,2))s"
Start-Sleep -Milliseconds 800
$log = (Get-ChildItem "$root\logs" -Filter 'engine-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
"`n--- 引擎侧 req done / throughput ---"
Select-String -Path $log -Pattern 'req#\d+ done|throughput \| 5\.0s \| decode' | Select-Object -Last 4 -ExpandProperty Line
"`n--- 启动行（确认 --spec 生效痕迹）---"
Select-String -Path $log -Pattern 'engine ready|capacity \||spec|mtp' | Select-Object -First 6 -ExpandProperty Line
