# local_train.ps1 -- 5070 Ti（12 GB）上一条命令跑完本地后训练
#
# 用法（在 D:\BaiduNetdiskDownload\Local-AI 下）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File train\lines\27b-kittyrev\kitty-rev\deploy\local_train.ps1
#   ... -DryRun                 # 只做「解包判断 + 体检 + 参数干跑」，不加载模型
#   ... -Steps 80 -Ga 8         # 覆盖步数/累积
#   ... -SkipExtract            # pack 已解包（会核 merged-layers/act-cache 在不在）
#
# 它做什么：
#   ① 解包 kittyrev-local-pack.tar（缺 merged-layers/ 或 act-cache/ 才解）
#   ② 体检：16 层 + head + index + 4388 .pt（调 deploy/verify_local_pack.py --dir）
#   ③ 显存守卫：nvidia-smi 可用 < 11 GiB 就警告（12 GB 卡要留桌面/浏览器）
#   ④ 干跑：train_partial_lora.py --dry-run 先验参数（尤其 --data-mix 的 Windows 盘符）
#   ⑤ 真训：4bit + cut=48..63 + LoRA，日志落 logs/local-train-<ts>.log，每 10 步打 vram peak
#
# 为什么参数是这一套：
#   · 只训后 16 层（48..63）：前 48 层用云端算好的 act-cache，显存只需装 16 层 4bit + head
#   · 实测同等配置峰值 6.71 GiB / 1.52 s/micro-step（docs-local-partial-lora.md §12）
#   · --data-mix 的 name 与 path 是独立字段：name 只是标识，path 不存在才 FATAL
#   · --eval-cache 必须全是 -val 目录（给 train 目录会 FATAL：val_loss==train_loss）

param(
  [string]$Root      = "D:\BaiduNetdiskDownload\Local-AI\train",
  [string]$Pack      = "",
  [string]$BaseConfig = "",
  [int]$Steps        = 160,
  [int]$Ctx          = 512,
  [int]$Ga           = 8,
  [int]$LoraR        = 16,
  [int]$EvalEvery    = 20,
  [double]$MinFreeGiB = 11.0,
  [switch]$SkipExtract,
  [switch]$SkipVerify,
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
# 子进程（python）按 UTF-8 输出；控制台也切 UTF-8，否则中文在 cp936 下变乱码
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$Repo   = Split-Path $Root -Parent                            # ...\Local-AI（$Root 是 train）
$Local  = Join-Path $Root "local-pack"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Train  = Join-Path $Repo "train\lines\27b-kittyrev\kitty-rev\scripts\train_partial_lora.py"
$Verify = Join-Path $Repo "train\lines\27b-kittyrev\kitty-rev\deploy\verify_local_pack.py"
if (-not $Pack) { $Pack = Join-Path $Local "kittyrev-local-pack.tar" }
$Ts     = Get-Date -Format "yyyyMMdd-HHmmss"
$LogDir = Join-Path $Repo "train\lines\27b-kittyrev\kitty-rev\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log    = Join-Path $LogDir "local-train-$Ts.log"

function Say($m) { Write-Host ""; Write-Host "===== $m =====" -ForegroundColor Cyan }
function Die($m) { Write-Host "[FATAL] $m" -ForegroundColor Red; exit 1 }

Say "0) 环境"
if (-not (Test-Path $Python)) { Die "找不到 python：$Python" }
if (-not (Test-Path $Train))  { Die "找不到训练脚本：$Train" }
$free = (Get-PSDrive D).Free / 1GB
Write-Host ("  python  = {0}" -f $Python)
Write-Host ("  D: 可用 = {0:N1} GiB（解包约需 25 GiB，保留原 tar 再 +24 GiB）" -f $free)
if ($free -lt 55) { Write-Host "  [warn] 可用空间 < 55 GiB：解包后可能不够训练产物" -ForegroundColor Yellow }

Say "1) 解包"
$needExtract = -not $SkipExtract -and
               (-not (Test-Path (Join-Path $Local "merged-layers")) -or
                -not (Test-Path (Join-Path $Local "act-cache")))
if ($SkipExtract) {
  Write-Host "  -SkipExtract：只核目录在不在"
  if (-not (Test-Path (Join-Path $Local "merged-layers"))) { Die "缺 $Local\merged-layers" }
  if (-not (Test-Path (Join-Path $Local "act-cache")))     { Die "缺 $Local\act-cache" }
} elseif ($needExtract) {
  if (-not (Test-Path $Pack)) { Die "找不到 pack：$Pack" }
  $ps = (Get-Item $Pack).Length / 1GB
  Write-Host ("  解包 {0}（{1:N1} GiB）→ {2} …（约 10-20 min，磁盘读为主）" -f $Pack, $ps, $Local)
  & tar.exe -xf $Pack -C $Local
  if ($LASTEXITCODE -ne 0) { Die "tar 解包失败（rc=$LASTEXITCODE）" }
  Write-Host "  [ok] 解包完成"
} else {
  Write-Host "  已解包（merged-layers/ + act-cache/ 都在），跳过"
}

# 1b) config.json：pack 的 merged-layers 只带 16 层 + head + index，
#     而 train_partial_lora 的 SplitSource 必须读 <layer-dir>/config.json 才能派生模型结构。
$Cfg = Join-Path $Local "merged-layers\config.json"
if (-not (Test-Path $Cfg)) {
  $cands = @($BaseConfig,
             (Join-Path $Root "kitty-rev/deploy/base-meta/config.json"),
             (Join-Path $Root "base\Qwen3.8-27B\config.json"),
             (Join-Path $Root "base\Qwen3-8B\config.json")) |
           Where-Object { $_ -and (Test-Path $_) }
  if (-not $cands) { Die "缺 merged-layers\config.json，本地也找不到 base 的 config.json（用 -BaseConfig 指定）" }
  Copy-Item $cands[0] $Cfg -Force
  Write-Host ("  [config] pack 没带 config.json → 从 {0} 复制" -f $cands[0])
} else {
  Write-Host "  [config] merged-layers\config.json 已在"
}

Say "2) 体检"
if ($SkipVerify) {
  Write-Host "  -SkipVerify：跳过 sha/结构检查（不推荐）"
} else {
  & $Python $Verify --dir $Local --json (Join-Path $LogDir "pack-verify-$Ts.json")
  if ($LASTEXITCODE -ne 0) { Die "pack 体检没过（见上）——不要开始训练" }
}

Say "3) 显存守卫"
# nvidia-smi 不一定在 PATH 里（本机在 System32，但被裁过 PATH 的 shell 找不到）
$smi = (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue).Source
if (-not $smi) {
  $smi = @("$env:SystemRoot\System32\nvidia-smi.exe",
           "C:\Windows\System32\nvidia-smi.exe",
           "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
           "C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe") |
         Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $smi) {
  Write-Host "  [warn] 找不到 nvidia-smi：跳过显存守卫（训练仍会因 OOM 失败，先自己确认显卡空着）" -ForegroundColor Yellow
  $q = $null
} else {
  Write-Host "  nvidia-smi = $smi"
  $q = & $smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader,nounits 2>$null
  if (-not $q) { Write-Host "  [warn] nvidia-smi 无输出：跳过显存守卫" -ForegroundColor Yellow }
}
if ($q) {
  $parts = ($q -split ",") | ForEach-Object { $_.Trim() }
  Write-Host ("  {0}  total={1} MiB  used={2} MiB  free={3} MiB" -f $parts[0], $parts[1], $parts[2], $parts[3])
  $freeGiB = [double]$parts[3] / 1024
} else {
  $freeGiB = 999.0
}
if ($freeGiB -lt $MinFreeGiB) {
  Write-Host ("  [warn] 可用 {0:N1} GiB < {1:N1} GiB：训练峰值实测 6.71 GiB，余量会被桌面/浏览器挤掉。" -f $freeGiB, $MinFreeGiB) -ForegroundColor Yellow
  Write-Host "         建议先关浏览器/其他 CUDA 进程，或把 -Ctx 降到 384。" -ForegroundColor Yellow
} else {
  Write-Host ("  [ok] 可用 {0:N1} GiB ≥ {1:N1} GiB（峰值 6.71 GiB）" -f $freeGiB, $MinFreeGiB) -ForegroundColor Green
}

Say "4) 组装参数"
$Act = Join-Path $Local "act-cache"
$Mix = "forge-train:$Act\forge-train:4,re-train:$Act\re-train:2,rest:$Act\rest:1"
$Eval = "re-val:$Act\re-val,forge-val:$Act\forge-val,gen-val:$Act\gen-val"
$Out = Join-Path $Repo "train\lines\27b-kittyrev\kitty-rev\out-local"

$argv = @(
  $Train,
  "--layer-dir", (Join-Path $Local "merged-layers"),
  "--from", "48", "--to", "63",
  "--head", (Join-Path $Local "merged-layers\head.safetensors"),
  "--data-mix", $Mix,
  "--eval-cache", $Eval,
  "--eval-by-cat",
  "--ctx", "$Ctx", "--lora-r", "$LoraR", "--bs", "1", "--ga", "$Ga",
  "--max-steps", "$Steps", "--dtype", "4bit",
  "--max-vram-gb", "11", "--ce-chunk", "128",
  "--log-every", "10", "--eval-every", "$EvalEvery",
  "--out", $Out
)
Write-Host "  data-mix : $Mix"
Write-Host "  eval     : $Eval"
Write-Host "  schedule : layers 48-63 · r=$LoraR · ctx=$Ctx · bs=1 · ga=$Ga · steps=$Steps · 4bit"

Say "5) 干跑（--dry-run，验证路径与参数，不加载模型）"
& $Python @argv --dry-run
if ($LASTEXITCODE -ne 0) { Die "干跑失败：先修参数（常见：--data-mix 的 path 不存在 / --eval-cache 给了 train 目录）" }

if ($DryRun) {
  Write-Host ""
  Write-Host "[done] -DryRun：只验到干跑。去掉 -DryRun 即开始训练。" -ForegroundColor Green
  exit 0
}

Say "6) 训练（日志：$Log）"
Write-Host "  每 10 步会打一行 vram_peak；Ctrl-C 可停，重跑加 --resume 接着训" -ForegroundColor DarkGray
& $Python @argv 2>&1 | Tee-Object -FilePath $Log
$rc = $LASTEXITCODE

Say "7) 结果"
if ($rc -ne 0) { Write-Host "[FAIL] rc=$rc  日志：$Log" -ForegroundColor Red; exit $rc }
$arts = Get-ChildItem $Out -Recurse -Filter "adapter_model.safetensors" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($arts) {
  Write-Host ("  adapter = {0}  ({1:N1} MiB)" -f $arts.FullName, ($arts.Length / 1MB)) -ForegroundColor Green
} else {
  Write-Host "  [warn] 没找到 adapter_model.safetensors，检查 $Out" -ForegroundColor Yellow
}
Write-Host "  日志 = $Log"
Write-Host "[done] 本地训练完成" -ForegroundColor Green
exit 0
