# 训练结束后自动串：merge → bf16 → Q6_K(主) + Q5_K_M-imatrix(备) → 三能力 + 四档上下文召回
# 用法: pwsh -File _work\rebuild\post_train_chain.ps1 [-SkipWait] [-Ctx "32768,65536,131072,262144"]
param(
  [switch]$SkipWait,
  [string]$Ctx = '32768,65536,131072,262144',
  [int]$Port = 8096
)
$ErrorActionPreference = 'Stop'
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$PY = "$ROOT\train\.venv\Scripts\python.exe"
$BASE = "$ROOT\train\lines\9b-oxcoder\models\OxCoder-9B"
$ADAPTER = "$ROOT\train\lines\9b-oxcoder\out\b1-oxcoder-nsfw-kitty\adapter"
$MERGED = "$ROOT\train\lines\9b-oxcoder\models\b1-merged"
$BF16 = "$ROOT\models\9b\gguf\kittyrev9b-b1-bf16.gguf"
$Q6 = "$ROOT\models\9b\gguf\kittyrev9b-b1-Q6_K.gguf"
$Q5 = "$ROOT\models\9b\gguf\kittyrev9b-b1-Q5_K_M-imx.gguf"
$IMX = "$ROOT\_work\quant\imatrix-b1.dat"
$CALIB = "$ROOT\_work\quant\calib-b1.txt"
$LOG = "$ROOT\train\logs\post-train-chain-$(Get-Date -Format yyyyMMdd-HHmm).log"
$BIN = "$ROOT\engines\llama-cpp\llama-bin"
$env:PYTHONIOENCODING = 'utf-8'

function Log($m) { $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; Write-Host $line; Add-Content -Path $LOG -Value $line -Encoding UTF8 }

Log "chain 启动（log=$LOG）"

# ---------- 0 等训练结束 ----------
if (-not $SkipWait) {
  Log '等待训练进程退出…'
  $spin = 0
  while ($true) {
    $done = $false
    $latest = Get-ChildItem "$ROOT\train\logs\b1-train-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) { $done = (Select-String -Path $latest.FullName -Pattern '\[done\] adapter' -Quiet) }
    # 用 CommandLine 判定（Get-Process .Path 常为空，不可靠）
    $trainer = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
                 Where-Object { $_.CommandLine -like '*train_qlora.py*' }
    if ($done -or -not $trainer) { break }
    Start-Sleep -Seconds 30; $spin++
    if ($spin % 10 -eq 0) { Log "  等待中… 已 $([int]($spin/2)) 分钟" }
  }
  Log '训练进程已退出，开始后处理'
}

# ---------- 1 merge ----------
if (-not (Test-Path "$ADAPTER\adapter_model.safetensors")) { throw "缺 adapter: $ADAPTER" }
if (Test-Path "$MERGED\config.json") { Log 'SKIP merge（已存在）' }
else {
  Log 'merge LoRA → HF'
  & $PY "$ROOT\train\lines\_shared\scripts\local_merge_lora.py" --base $BASE --adapter $ADAPTER --out $MERGED
  if ($LASTEXITCODE -ne 0) { throw "merge 失败 $LASTEXITCODE" }
}

# ---------- 2 bf16 GGUF ----------
if (Test-Path $BF16) { Log 'SKIP bf16（已存在）' }
else {
  Log 'convert → bf16 GGUF'
  Push-Location "$ROOT\train\lines\_shared\tools\lc"
  try {
    & $PY 'convert_hf_to_gguf.py' $MERGED --outfile $BF16 --outtype bf16
    if ($LASTEXITCODE -ne 0) { throw "convert 失败 $LASTEXITCODE" }
  } finally { Pop-Location }
}

# ---------- 3 量化 ----------
if (Test-Path $Q6) { Log 'SKIP Q6_K（已存在）' }
else {
  Log 'quantize Q6_K（主投）'
  & "$BIN\llama-quantize.exe" $BF16 $Q6 Q6_K 16
  if ($LASTEXITCODE -ne 0) { throw "Q6_K 失败" }
}
if (-not (Test-Path $IMX) -and (Test-Path $CALIB)) {
  Log 'imatrix（备档用）'
  & "$BIN\llama-imatrix.exe" $CALIB -m $BF16 -o $IMX --chunks 200 -ngl 99
}
if ((Test-Path $IMX) -and -not (Test-Path $Q5)) {
  Log 'quantize Q5_K_M + imatrix（备档）'
  & "$BIN\llama-quantize.exe" --imatrix $IMX $BF16 $Q5 Q5_K_M 16
}

Get-ChildItem "$ROOT\models\9b\gguf" -Filter 'kittyrev9b-b1-*' | ForEach-Object { Log ("  产物 {0} {1:N2} GB" -f $_.Name, ($_.Length / 1GB)) }

# ---------- 4 三能力探针（短上下文服务） ----------
function Start-Srv([string]$model, [int]$ctx) {
  $p = Start-Process -FilePath "$BIN\llama-server.exe" -ArgumentList @(
    '-m', $model, '--port', "$Port", '-c', "$ctx", '-ctk', 'q4_0', '-ctv', 'q4_0',
    '-ngl', '99', '-fa', 'on', '--jinja', '--reasoning-format', 'none', '--no-warmup'
  ) -RedirectStandardOutput "$ROOT\_work\quant\srv-$ctx.log" -RedirectStandardError "$ROOT\_work\quant\srv-$ctx.err" -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 150; $i++) {
    Start-Sleep -Seconds 2
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3; return $p } catch { }
  }
  Log "  服务启动失败 ctx=$ctx（见 srv-$ctx.err）"
  return $null
}

$srv = Start-Srv $Q6 16384
if ($srv) {
  Log '三能力探针（Q6_K）'
  & $PY "$ROOT\_work\quant\verify_tiers.py" --port $Port --model $Q6 --tag Q6_K 2>&1 | Add-Content -Path $LOG -Encoding UTF8
  Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 5
}

# ---------- 5 四档上下文召回 ----------
foreach ($c in ($Ctx -split ',')) {
  $ci = [int]$c
  $srv = Start-Srv $Q6 $ci
  if (-not $srv) { continue }
  Log "长上下文召回 ctx=$ci"
  & $PY "$ROOT\_work\quant\verify_longctx.py" --port $Port --model $Q6 --ctx $ci 2>&1 | Add-Content -Path $LOG -Encoding UTF8
  Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 5
}

Log 'chain 完成'

