# v5_sentinel.ps1 —— 开机哨兵：轮询 → 自动上传 → 自动起 v5_auto.py → 落状态
#
# 为什么需要它：操作者不监督，也不会告诉我几点开机。哨兵在本机后台盯着，
# 一旦云端 SSH 通，立刻把 8 个文件推上去并起编排脚本，全程无人干预。
#
# 判据：
#   · SSH 通 + 能读到 GPU 型号 = 开机完成（不是刚通电的几十秒）
#   · 上传后云端自检通过（文件就位 + 语法 OK + 静态核对全绿）= 可以起 auto
#   · 起 auto 后写 STATUS，lead 据此跟进
#
# 用法：pwsh -NoProfile -File deploy\v5_sentinel.ps1
#       状态文件：logs\v5\SENTINEL.json

$ErrorActionPreference = 'Continue'
$Repo = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev'
$env:AUTODL_HOST = if ($env:AUTODL_HOST) { $env:AUTODL_HOST } else { '123.127.15.155' }
$Py   = 'C:\ProgramData\anaconda3\python.exe'
$Stat = Join-Path $Repo 'logs\v5\SENTINEL.json'
$Poll = 30

function Write-Stat($obj) {
    $obj | ConvertTo-Json -Depth 5 | Set-Content -Path $Stat -Encoding utf8
}

Write-Stat @{ state='polling'; since=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); host=$env:AUTODL_HOST; tries=0 }

$tries = 0
while ($true) {
    $tries++
    $up = $false
    $info = ''
    try {
        $r = & $Py "$Repo\deploy\remote.py" --cmd 'nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1; echo "---"; df -BG --output=avail /root/autodl-tmp | tail -1' 2>&1
        $txt = ($r -join "`n")
        if ($txt -match 'GPU|MiB|G\s*$' -and $txt -notmatch 'Traceback|Connection|timed out|refused') {
            if ($txt -match '\d+\s*MiB' -or $txt -match '\d+G') {
                $up = $true
                $info = ($txt -split "`n" | Where-Object { $_.Trim() } | Select-Object -First 3) -join ' | '
            }
        }
    } catch { }

    Write-Host ("[{0}] try={1} up={2} {3}" -f (Get-Date -Format 'HH:mm:ss'), $tries, $up, $info)

    if (-not $up) {
        Write-Stat @{ state='polling'; since=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); host=$env:AUTODL_HOST; tries=$tries; last=$info }
        Start-Sleep -Seconds $Poll
        continue
    }

    # ---- 开机确认：再等 20 秒让 sshd/驱动就绪 ----
    Start-Sleep -Seconds 20
    Write-Stat @{ state='uploading'; since=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); host=$env:AUTODL_HOST; tries=$tries; info=$info; upload_start=(Get-Date -Format 'HH:mm:ss') }

    Write-Host "===== 上传 ====="
    $up_out = & pwsh -NoProfile -File "$Repo\deploy\v5_upload.ps1" 2>&1
    $up_txt = ($up_out -join "`n")
    $up_out | Select-Object -Last 25 | ForEach-Object { Write-Host $_ }

    # ---- 上传后的自检必须过（文件就位 + 语法 + 静态核对）----
    $selfcheck_ok = ($up_txt -match '\[VERDICT\] 全部通过') -and ($up_txt -notmatch 'MISS data/intent3')
    if (-not $selfcheck_ok) {
        Write-Stat @{ state='upload_selfcheck_failed'; since=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); host=$env:AUTODL_HOST; tries=$tries; tail=($up_out | Select-Object -Last 12) }
        Write-Host "[FATAL] 上传后自检未过，停。状态见 $Stat"
        exit 1
    }

    # ---- 起编排（后台，脱离 ssh）----
    Write-Host "===== 起 v5_auto.py（后台）====="
    Write-Stat @{ state='starting_auto'; since=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'); host=$env:AUTODL_HOST; tries=$tries; upload_ok=$true }

    $bg = & $Py "$Repo\deploy\remote.py" --bg "cd /root/autodl-tmp/kitty-rev && mkdir -p logs/v5 && /root/miniconda3/bin/python tools/v5_auto.py >> logs/v5/AUTO-V5.log 2>&1" 2>&1
    $bg | ForEach-Object { Write-Host $_ }

    Write-Stat @{
        state='auto_started'
        since=(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        host=$env:AUTODL_HOST
        tries=$tries
        info=$info
        bg=($bg -join ' ')
        note='下一步：读 logs/v5/AUTO-V5.log 与 logs/v5/PR-*.md 跟进；跑完回传 + 手动关机'
    }
    Write-Host "===== 哨兵完成，auto 已起 ====="
    break
}
