# v6_s5_fetch.ps1 — V6 S5 一键回传 + md5 双端校验 + 通过即关机
#
# 为什么要有这个脚本：
#   V5 时期在传输上踩过两次血亏 —— 并发写同一 .part 导致 size 对、magic 对、md5 错。
#   把它做成脚本 = 一个目标文件只用一个下载进程、md5 不一致就绝不关机、md5 一致就立刻关机（不空烧）。
#
# 用法：
#   & 'C:\Program Files (x86)\PowerShell\7\pwsh.exe' -File v6_s5_fetch.ps1
#   & ... -File v6_s5_fetch.ps1 -NoShutdown     # 只下载校验，不关机
#
# 退出码：0 = md5 通过（并按需关机）｜3 = md5 不一致（未关机）｜4 = 远程文件迟迟不出现

param(
    [string]$Remote = "/root/autodl-tmp/kitty-rev/ninfer-v6/qwen3.8-27b-kittyrev-v6-iq2s-mtp.ninfer",
    [string]$Local  = "D:\BaiduNetdiskDownload\Local-AI\train\local-pack\qwen3.8-27b-kittyrev-v6-iq2s-mtp.ninfer",
    [int]$Streams   = 48,
    [int]$WaitMin   = 60,
    [switch]$NoShutdown,
    [switch]$SkipWaitStable
)

$ErrorActionPreference = 'Continue'
$py   = 'C:\ProgramData\anaconda3\python.exe'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$log  = Join-Path $root "logs\v6\S5-FETCH.log"
$null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log)

$env:AUTODL_HOST = 'connect.bjb1.seetacloud.com'
$env:AUTODL_PORT = '35299'
$env:AUTODL_PASS = 'gpMW8alzDfoL'

function W([string]$m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $m"
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

function Remote([string]$cmd) {
    & $py (Join-Path $here 'remote.py') --cmd $cmd 2>&1
}

W "=== S5 START remote=$Remote"

# ── 1) 等远程文件出现并稳定（连续两次 size 相同且 >1GB）──────────────
if (-not $SkipWaitStable) {
    $t0 = Get-Date
    $prev = -1
    while (((Get-Date) - $t0).TotalMinutes -lt $WaitMin) {
        $line = (Remote "stat -c %s $Remote 2>/dev/null || echo 0" | Where-Object { $_ -match '^\d+$' } | Select-Object -Last 1)
        $sz = 0; [int64]::TryParse("$line", [ref]$sz) | Out-Null
        W "remote size=$sz (prev=$prev)"
        if ($sz -gt 1000000000 -and $sz -eq $prev) { W "size 稳定 = $sz"; break }
        $prev = $sz
        Start-Sleep -Seconds 30
    }
    if ($prev -lt 1000000000) { W "FAIL 远程文件未就绪（最后 size=$prev）"; exit 4 }
}

# ── 2) 远程 md5 ────────────────────────────────────────────────
$rmd5line = Remote "md5sum $Remote | cut -d' ' -f1" | Where-Object { $_ -match '^[0-9a-f]{32}$' } | Select-Object -Last 1
if (-not $rmd5line) { W "FAIL 取不到远程 md5"; exit 4 }
$rmd5 = "$rmd5line".Trim().ToLower()
W "remote md5=$rmd5"

# ── 3) 下载（单进程，独占目标文件）─────────────────────────────────
if (Test-Path $Local) { W "本地已存在，先删：$Local"; Remove-Item -LiteralPath $Local -Force -ErrorAction SilentlyContinue }
Get-ChildItem (Split-Path -Parent $Local) -Filter ((Split-Path -Leaf $Local) + ".part*") -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }
W "开始下载 streams=$Streams"
$dlOut = & $py (Join-Path $here 'get_multi.py') --remote $Remote --local $Local --streams $Streams --reset-parts 2>&1
$dlrc = $LASTEXITCODE
$dlOut | Select-Object -Last 5 | ForEach-Object { W "  dl| $_" }
W "下载完成 rc=$dlrc"

if (-not (Test-Path $Local)) { W "FAIL 本地文件不存在"; exit 3 }

# ── 4) 本机 md5 + 三方核验 ─────────────────────────────────────
$lmd5 = (Get-FileHash -LiteralPath $Local -Algorithm MD5).Hash.ToLower()
$lsz  = (Get-Item -LiteralPath $Local).Length
$fs   = [System.IO.File]::OpenRead($Local); $buf = New-Object byte[] 4; $null = $fs.Read($buf, 0, 4); $fs.Close()
$magic = [System.Text.Encoding]::ASCII.GetString($buf)
W "local  md5=$lmd5  size=$lsz  magic=$magic"

$ok = ($lmd5 -eq $rmd5) -and ($magic -eq 'NINF') -and ($lsz -lt 10737418240)
if (-not $ok) {
    W "FAIL 校验不通过：md5一致=$($lmd5 -eq $rmd5) magic=NINF=$($magic -eq 'NINF') size<10GiB=$($lsz -lt 10737418240)"
    W "⇒ 不关机（保留现场，防止把坏件当成交付）"
    exit 3
}
W "PASS md5 双端一致 · magic=NINF · size=$([math]::Round($lsz/1GB,4)) GiB < 10 GiB"

# ── 5) 立刻关机（远程任务到此结束）────────────────────────────
if ($NoShutdown) { W "NoShutdown 指定，跳过关机"; exit 0 }
W "远程任务完成 → 立即关机"
$offOut = & $py (Join-Path $here 'autodl_power.py') off --wait 300 2>&1
$offrc = $LASTEXITCODE
$offOut | ForEach-Object { W "  off| $_" }
W "S5 DONE rc=$offrc"
exit 0
