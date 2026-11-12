param(
  [int]$SleepSec = 0,
  [string]$LogPath = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\logs\v4\MONITOR2.log'
)

$ErrorActionPreference = 'Stop'
$env:AUTODL_HOST = '123.127.15.155'
$py = 'C:\ProgramData\anaconda3\python.exe'
$remote = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\deploy\remote.py'

$cmdStr = 'date +%H:%M; tail -c 600 /root/autodl-tmp/kitty-rev/logs/v4/train2.log | tr ''\r'' ''\n'' | grep -E ''[0-9]+/915'' | tail -1; nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw --format=csv,noheader; df -h /root/autodl-tmp | tail -1; pgrep -f train_kitty | wc -l'

if ($SleepSec -gt 0) { Start-Sleep -Seconds $SleepSec }

$raw = & $py $remote --cmd $cmdStr 2>&1 | Out-String
$lines = $raw -split "`r?`n" | Where-Object { $_.Trim() -ne '' }

$timeStr = '??:??'
$progStr = ''
$gpuStr = ''
$dfStr = ''
$aliveCnt = ''

foreach ($l in $lines) {
  $t = $l.Trim()
  if ($t -match '^\d{2}:\d{2}$') { $timeStr = $t; continue }
  if ($t -match '(\d+)/915') { $progStr = $t; continue }
  if ($t -match 'MiB') { $gpuStr = $t; continue }
  if ($t -match '^/dev/') { $dfStr = $t; continue }
  if ($t -match '^\d+$') { $aliveCnt = $t; continue }
}

$step = '?'
$sit = '?'
if ($progStr -match '(\d+)/915') { $step = $Matches[1] }
if ($progStr -match '([\d.]+)s/it') { $sit = $Matches[1] }
elseif ($progStr -match '([\d.]+)it/s') { $sit = $Matches[1] }

$nums = [regex]::Matches($gpuStr, '[\d.]+') | ForEach-Object { $_.Value }
$gpuFmt = if ($nums.Count -ge 3) { "$($nums[0])%, $($nums[1]) MiB, $($nums[2]) W" } else { $gpuStr.Trim() }
$alive = if ([int]$aliveCnt -gt 0) { 1 } else { 0 }

$line = "$timeStr | step=$step/915 | ${sit}s/it | $gpuFmt | alive=$alive"
Add-Content -Path $LogPath -Value $line -Encoding UTF8
Write-Output $line
Write-Output "RAW:"
Write-Output $raw
Write-Output "DF: $dfStr"
Write-Output "ALIVE_RAW: $aliveCnt"
