# watch_fetch61b.ps1 — 后台盯回传，落地后校验 md5，通过则远程关机
#
# 判据（三条全过才关机，任一不过保留实例防误关）：
#   ① 本地 FINAL size == 10,506,255,104
#   ② 本地 md5    == da8cc82fc4c760177e06b9b38756ccd7
#   ③ magic       == NINF
# 关机用 autodl_power.py off（与之前手动关机同一路径，已验证 16s 完成）

$ErrorActionPreference = 'Continue'
$root   = 'D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev'
$target = 'D:\BaiduNetdiskDownload\Local-AI\train\local-pack\qwen3.8-27b-kittyrev-v61b-iq2s-mtp.ninfer'
$expectSize = 10506255104
$expectMd5  = 'da8cc82fc4c760177e06b9b38756ccd7'
$log = Join-Path $root 'logs\v6\WATCH-FETCH61B.log'

function W($m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $m"
    Add-Content -Path $log -Value $line -Encoding utf8
}

W "=== WATCH START  target=$target"

# 1) 等 get_multi 退出（最多 40 分钟）
$deadline = (Get-Date).AddMinutes(40)
while ((Get-Date) -lt $deadline) {
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
             Where-Object { $_.CommandLine -like '*get_multi*' }
    if (-not $procs) { W "get_multi 已退出"; break }
    Start-Sleep -Seconds 30
}
Start-Sleep -Seconds 5

# 2) 三判
if (-not (Test-Path $target)) {
    W "FAIL 目标文件不存在 → 不关机"
    exit 4
}
$fi  = New-Object System.IO.FileInfo($target)
$sz  = $fi.Length
$md5 = (Get-FileHash -LiteralPath $target -Algorithm MD5).Hash.ToLower()
$fs  = [System.IO.File]::OpenRead($target)
$buf = New-Object byte[] 4
$null = $fs.Read($buf, 0, 4)
$fs.Close()
$magic = [System.Text.Encoding]::ASCII.GetString($buf)

W "FINAL size=$sz  md5=$md5  magic=$magic"
W "EXPECT size=$expectSize  md5=$expectMd5  magic=NINF"

$okSize  = ($sz -eq $expectSize)
$okMd5   = ($md5 -eq $expectMd5)
$okMagic = ($magic -eq 'NINF')

if (-not ($okSize -and $okMd5 -and $okMagic)) {
    W "FAIL 校验不通过 size=$okSize md5=$okMd5 magic=$okMagic → 保留实例，不关机"
    exit 3
}

W "PASS 三判全过 → 远程关机"
$env:AUTODL_HOST = 'connect.bjb1.seetacloud.com'
$env:AUTODL_PORT = '35299'
$env:AUTODL_PASS = 'gpMW8alzDfoL'
$out = & 'C:\ProgramData\anaconda3\python.exe' (Join-Path $root 'deploy\autodl_power.py') off 2>&1
$out | ForEach-Object { W "  power| $_" }
W "=== WATCH DONE"
