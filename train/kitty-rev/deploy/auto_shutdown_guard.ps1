# auto_shutdown_guard.ps1 — 远程实例硬超时关机兜底
#
# 背景：操作者要求「远程 4090 的任务完成后要立马自动关机」。
# 正常路径由 lead 在 S7 回传并校验 md5 后执行 autodl_power.py off；
# 本脚本是**兜底**：若主控失联 / 链路卡住 / 无人收口，到点强制关机，防止空烧。
#
# 用法：
#   & 'C:\Program Files (x86)\PowerShell\7\pwsh.exe' -File auto_shutdown_guard.ps1 -Deadline 06:45
#
# 判据：到 Deadline 时无论发生了什么，执行 autodl_power.py off --force，并把结果写日志。

param(
    [string]$Deadline = "06:45",
    [int]$PollSec = 120,
    [string]$LogPath = ""
)

$ErrorActionPreference = 'Continue'
$py = 'C:\ProgramData\anaconda3\python.exe'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $LogPath) { $LogPath = Join-Path (Split-Path -Parent $here) "logs\v6\SHUTDOWN-GUARD.log" }
$null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogPath)

function W([string]$m) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
    Write-Output $line
    Add-Content -Path $LogPath -Value $line -Encoding utf8
}

W "GUARD START deadline=$Deadline poll=${PollSec}s log=$LogPath"

while ($true) {
    $now = Get-Date
    $dlStr = $now.ToString('yyyy-MM-dd') + ' ' + $Deadline
    try {
        $dl = [datetime]::ParseExact($dlStr, 'yyyy-MM-dd HH:mm', $null)
    } catch {
        W "FATAL 无法解析 Deadline '$Deadline'，直接用 +1h 兜底"
        $dl = $now.AddHours(1)
    }
    if ($now -ge $dl) {
        W "DEADLINE reached ($($now.ToString('HH:mm'))) → 强制关机"
        $out = & $py (Join-Path $here 'autodl_power.py') off --force --wait 180 2>&1
        $out | ForEach-Object { W "  $_" }
        $rc = $LASTEXITCODE
        W "GUARD DONE rc=$rc"
        break
    }
    $remain = [int]($dl - $now).TotalMinutes
    W "alive remain=${remain}min"
    Start-Sleep -Seconds $PollSec
}
