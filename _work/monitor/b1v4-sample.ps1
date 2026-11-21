# b1v4 训练采样器（只读）
$ErrorActionPreference='SilentlyContinue'
$log='D:\BaiduNetdiskDownload\Local-AI\train\logs\b1v4-train-20261121-1325.log'
$err='D:\BaiduNetdiskDownload\Local-AI\train\logs\b1v4-train-20261121-1325.log.err'
$out='D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\b1v4-oxcoder-nsfw-kitty'
$smi='C:\Windows\System32\DriverStore\FileRepository\nvtfsi.inf_amd64_256471fdd09ac11c\nvidia-smi.exe'

$waitSec = if($args.Count -ge 1){[int]$args[0]}else{0}
if($waitSec -gt 0){
  $deadline=(Get-Date).AddSeconds($waitSec)
  while((Get-Date) -lt $deadline){
    $e = Get-Content $err -Raw
    if($e -match 'CUDA out of memory|Traceback'){ break }
    if((Get-Content $log -Raw) -match '\[done\] adapter'){ break }
    Start-Sleep -Seconds 15
  }
}

Write-Output "TIME=$(Get-Date -Format 'HH:mm:ss')"

# 进程
$shell = Get-Process -Id 17572
$body  = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*train_qlora.py*' }
Write-Output ("SHELL_PID=17572 alive=" + [bool]$shell)
foreach($b in $body){ Write-Output ("BODY_PID={0} PPID={1}" -f $b.ProcessId,$b.ParentProcessId) }
$gpuPids = & $smi --query-compute-apps=pid --format=csv,noheader
Write-Output ("GPU_PY_PIDS=" + (($gpuPids | Where-Object {$_ -match '^\d+$'}) -join ','))

# 最新 loss 行（stdout）
$lossLine = Select-String -Path $log -Pattern "'loss'" | Select-Object -Last 1 | ForEach-Object { $_.Line }
Write-Output ("LAST_LOSS_LINE=" + $lossLine)
# done 标记
$done = (Get-Content $log -Raw) -match '\[done\] adapter'
Write-Output ("DONE_MARKER=" + $done)

# tqdm 进度（err）
$tq = Get-Content $err -Tail 40 | Where-Object { $_ -match '\|\s*\d+/429' } | Select-Object -Last 1
if(-not $tq){ $tq = (Get-Content $err -Tail 40 | Where-Object { $_ -match 'it\]' } | Select-Object -Last 1) }
Write-Output ("TQDM=" + ($tq -replace '\s+$',''))

# 异常
$eTxt = Get-Content $err -Raw
if($eTxt -match 'CUDA out of memory'){ Write-Output "ALERT=OOM" }
if($eTxt -match 'nan|NaN|inf' ){ $t=(Get-Content $log -Raw); if($t -match "'loss': 'nan|'loss': 'inf"){ Write-Output "ALERT=NAN_INF" } }
# checkpoint
if(Test-Path $out){
  $cks = Get-ChildItem $out -Directory -Filter 'checkpoint-*' | Sort-Object Name
  foreach($c in $cks){
    $ts = Test-Path (Join-Path $c.FullName 'trainer_state.json')
    Write-Output ("CKPT={0} trainer_state={1} mtime={2}" -f $c.Name,$ts,$c.LastWriteTime.ToString('HH:mm:ss'))
  }
  if(-not $cks){ Write-Output "CKPT=none" }
} else { Write-Output "CKPT=outdir_missing" }

& $smi --query-gpu=memory.used,temperature.gpu,utilization.gpu,power.draw --format=csv,noheader
