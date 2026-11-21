# b1v3 训练后一条龙：merge → bf16 → Q6_K → 三能力 + NSFW 20条 + 四档召回
param([switch]$SkipWait, [int]$Port = 8097)
$ErrorActionPreference = 'Stop'
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$PY = "$ROOT\train\.venv\Scripts\python.exe"
$BASE = "$ROOT\train\lines\9b-oxcoder\models\OxCoder-9B"
$ADAPTER = "$ROOT\train\lines\9b-oxcoder\out\b1v3-oxcoder-nsfw-kitty\adapter"
$MERGED = "$ROOT\train\lines\9b-oxcoder\models\b1v3-merged"
$BF16 = "$ROOT\models\9b\gguf\kittyrev9b-b1v3-bf16.gguf"
$Q6 = "$ROOT\models\9b\gguf\kittyrev9b-b1v3-Q6_K.gguf"
$BIN = "$ROOT\engines\llama-cpp\llama-bin"
$LOG = "$ROOT\train\logs\post-v3-chain-$(Get-Date -Format yyyyMMdd-HHmm).log"
$env:PYTHONIOENCODING = 'utf-8'

function Log($m) { $s = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m; Write-Host $s; Add-Content -Path $LOG -Value $s -Encoding UTF8 }
function Alive { (Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*train_qlora.py*' } | Measure-Object).Count }

Log "v3 chain 启动（log=$LOG）"
if (-not $SkipWait) {
  Log '等待训练退出…'
  $i = 0
  while ($true) {
    $latest = Get-ChildItem "$ROOT\train\logs\b1v3-train-*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $done = $false
    if ($latest) { $done = Select-String -Path $latest.FullName -Pattern '\[done\] adapter' -Quiet }
    if ($done -or (Alive) -eq 0) { break }
    Start-Sleep -Seconds 30; $i++
    if ($i % 10 -eq 0) { Log "  等待中… 已 $([int]($i/2)) 分钟" }
  }
  Log '训练已退出'
}

if (-not (Test-Path "$ADAPTER\adapter_model.safetensors")) { throw "缺 adapter: $ADAPTER" }
if (-not (Test-Path "$MERGED\config.json")) {
  Log 'merge'
  & $PY "$ROOT\train\lines\_shared\scripts\local_merge_lora.py" --base $BASE --adapter $ADAPTER --out $MERGED
  if ($LASTEXITCODE -ne 0) { throw "merge 失败" }
}
if (-not (Test-Path $BF16)) {
  Log 'convert bf16'
  Push-Location "$ROOT\train\lines\_shared\tools\lc"
  try { & $PY 'convert_hf_to_gguf.py' $MERGED --outfile $BF16 --outtype bf16; if ($LASTEXITCODE -ne 0) { throw 'convert 失败' } } finally { Pop-Location }
}
if (-not (Test-Path $Q6)) {
  Log 'quantize Q6_K'
  & "$BIN\llama-quantize.exe" $BF16 $Q6 Q6_K 16
  if ($LASTEXITCODE -ne 0) { throw 'Q6_K 失败' }
}
Get-ChildItem "$ROOT\models\9b\gguf" -Filter 'kittyrev9b-b1v3-*' | ForEach-Object { Log ("  产物 {0} {1:N2} GB" -f $_.Name, ($_.Length / 1GB)) }

function StartSrv([int]$ctx) {
  $p = Start-Process -FilePath "$BIN\llama-server.exe" -ArgumentList @('-m', $Q6, '--port', "$Port", '-c', "$ctx",
    '-ctk', 'q4_0', '-ctv', 'q4_0', '-ngl', '99', '-fa', 'on', '--jinja', '--reasoning-format', 'none', '--no-warmup') `
    -RedirectStandardOutput "$ROOT\_work\quant\v3srv-$ctx.log" -RedirectStandardError "$ROOT\_work\quant\v3srv-$ctx.err" -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 150; $i++) { Start-Sleep -Seconds 2; try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3; return $p } catch { } }
  Log "  服务启动失败 ctx=$ctx"; return $null
}

$srv = StartSrv 16384
if ($srv) {
  Log '三能力探针'
  & $PY "$ROOT\_work\quant\verify_tiers.py" --port $Port --model $Q6 --tag b1v3 2>&1 | Add-Content -Path $LOG -Encoding UTF8
  Log 'NSFW 20 条零起点 + 3 条续写'
  & $PY "$ROOT\_work\quant\verify_nsfw.py" --port $Port --model $Q6 --tag b1v3 2>&1 | Add-Content -Path $LOG -Encoding UTF8
  Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 5
}
foreach ($c in 65536, 262144) {
  $srv = StartSrv $c
  if (-not $srv) { continue }
  Log "召回 ctx=$c"
  & $PY "$ROOT\_work\quant\verify_longctx.py" --port $Port --model $Q6 --ctx $c 2>&1 | Add-Content -Path $LOG -Encoding UTF8
  Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 5
}
Log 'v3 chain 完成'
