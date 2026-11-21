# B1 训练后一条龙：merge → bf16 → imatrix → 三档量化 → 验收
# 用法: pwsh -File _work\rebuild\run_quant.ps1 -Stage all|merge|gguf|imatrix|quant|verify
param([string]$Stage = 'all', [string]$Adapter = 'train\lines\9b-oxcoder\out\b1-oxcoder-nsfw-kitty\adapter')
$ErrorActionPreference = 'Stop'
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$PY = "$ROOT\train\.venv\Scripts\python.exe"
$BASE = "$ROOT\train\lines\9b-oxcoder\models\OxCoder-9B"
$MERGED = "$ROOT\train\lines\9b-oxcoder\models\b1-merged"
$BF16 = "$ROOT\models\9b\gguf\kittyrev9b-b1-bf16.gguf"
$IMX = "$ROOT\_work\quant\imatrix-b1.dat"
$CALIB = "$ROOT\_work\quant\calib-b1.txt"
$Q = "$ROOT\engines\llama-cpp\llama-bin\llama-quantize.exe"
$IM = "$ROOT\engines\llama-cpp\llama-bin\llama-imatrix.exe"
$Q5 = "$ROOT\models\9b\gguf\kittyrev9b-b1-Q5_K_M-imx.gguf"
$Q6 = "$ROOT\models\9b\gguf\kittyrev9b-b1-Q6_K.gguf"
$IQ4 = "$ROOT\models\9b\gguf\kittyrev9b-b1-IQ4_XS-imx.gguf"
$env:PYTHONIOENCODING = 'utf-8'

if ($Stage -in @('merge', 'all')) {
  if (Test-Path "$MERGED\config.json") { "SKIP merge" }
  else {
    "== merge"
    & $PY "$ROOT\train\lines\_shared\scripts\local_merge_lora.py" --base $BASE --adapter $ROOT\$Adapter --out $MERGED
    if ($LASTEXITCODE -ne 0) { throw "merge 失败 $LASTEXITCODE" }
  }
}
if ($Stage -in @('gguf', 'all')) {
  if (Test-Path $BF16) { "SKIP gguf" }
  else {
    "== bf16 gguf"
    Push-Location "$ROOT\train\lines\_shared\tools\lc"
    try {
      & $PY 'convert_hf_to_gguf.py' $MERGED --outfile $BF16 --outtype bf16
      if ($LASTEXITCODE -ne 0) { throw "convert 失败 $LASTEXITCODE" }
    } finally { Pop-Location }
  }
}
if ($Stage -in @('imatrix', 'all')) {
  if (Test-Path $IMX) { "SKIP imatrix" }
  else {
    if (-not (Test-Path $CALIB)) { throw "缺校准集 $CALIB（先跑 _work\quant\build_calib.py）" }
    "== imatrix"
    & $IM $CALIB -m $BF16 -o $IMX --chunks 200 -ngl 99
    if ($LASTEXITCODE -ne 0) { throw "imatrix 失败 $LASTEXITCODE" }
  }
}
if ($Stage -in @('quant', 'all')) {
  if (-not (Test-Path $BF16)) { throw "缺 $BF16" }
  if (-not (Test-Path $Q5)) {
    "== Q5_K_M + imatrix"
    & $Q --imatrix $IMX $BF16 $Q5 Q5_K_M 16
    if ($LASTEXITCODE -ne 0) { throw "Q5_K_M 失败" }
  }
  if (-not (Test-Path $Q6)) {
    "== Q6_K"
    & $Q $BF16 $Q6 Q6_K 16
    if ($LASTEXITCODE -ne 0) { throw "Q6_K 失败" }
  }
  if (-not (Test-Path $IQ4)) {
    "== IQ4_XS + imatrix"
    & $Q --imatrix $IMX $BF16 $IQ4 IQ4_XS 16
    if ($LASTEXITCODE -ne 0) { throw "IQ4_XS 失败" }
  }
}
"== 产物"
Get-ChildItem "$ROOT\models\9b\gguf" -Filter 'kittyrev9b-b1-*' -ErrorAction SilentlyContinue |
  Select-Object Name, @{n = 'GB'; e = { [math]::Round($_.Length / 1GB, 2) } } | Format-Table -AutoSize
