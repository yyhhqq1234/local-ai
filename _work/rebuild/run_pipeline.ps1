# A 路线一键流水：合并 → GGUF bf16 → Q5_K_M
# 用法（仓库根）：pwsh -File _work\rebuild\run_pipeline.ps1 [-Stage merge|convert|quant|all]
param([string]$Stage = 'all')
$ErrorActionPreference = 'Stop'
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT

$BASE = "$ROOT\train\lines\9b-oxcoder\models\Qwen3.5-9B"
$ADAPTER = "$ROOT\train\lines\9b-oxcoder\out\2b-nsfw-final"
$MERGED = "$ROOT\train\lines\9b-oxcoder\models\kittyrev-nsfw-merged"
$BF16 = "$ROOT\models\9b\gguf\kittyrev9b-nsfw-bf16.gguf"
$Q5 = "$ROOT\models\9b\gguf\kittyrev9b-nsfw-Q5_K_M.gguf"
$PY = "$ROOT\train\.venv\Scripts\python.exe"
$CONV_DIR = "$ROOT\train\lines\_shared\tools\lc"
$QUANT = "$ROOT\engines\llama-cpp\llama-bin\llama-quantize.exe"

function Check-Shards {
  $need = 4
  $got = @(Get-ChildItem $BASE -Filter 'model.safetensors-*.safetensors' -ErrorAction SilentlyContinue |
           Where-Object { $_.Length -gt 4GB })
  if ($got.Count -lt $need) { throw "基座分片不全：$($got.Count)/$need（先等下载完成）" }
  "分片齐：$($got.Count)/$need"
}

if ($Stage -in @('merge','all')) {
  Check-Shards
  if (Test-Path "$MERGED\config.json") { "SKIP merge（已存在 $MERGED）" }
  else {
    "== merge（分片级，RAM<6GB）"
    & $PY "$ROOT\train\lines\_shared\scripts\local_merge_lora.py" --base $BASE --adapter $ADAPTER --out $MERGED
    if ($LASTEXITCODE -ne 0) { throw "merge 失败 exit=$LASTEXITCODE" }
  }
}

if ($Stage -in @('convert','all')) {
  if (Test-Path $BF16) { "SKIP convert（已存在 $BF16）" }
  else {
    "== convert → bf16 gguf"
    Push-Location $CONV_DIR
    try {
      & $PY 'convert_hf_to_gguf.py' $MERGED --outfile $BF16 --outtype bf16
      if ($LASTEXITCODE -ne 0) { throw "convert 失败 exit=$LASTEXITCODE" }
    } finally { Pop-Location }
  }
}

if ($Stage -in @('quant','all')) {
  if (-not (Test-Path $BF16)) { throw "缺 $BF16" }
  if (Test-Path $Q5) { "SKIP quant（已存在 $Q5）" }
  else {
    "== quantize Q5_K_M"
    & $QUANT $BF16 $Q5 Q5_K_M 16
    if ($LASTEXITCODE -ne 0) { throw "quantize 失败 exit=$LASTEXITCODE" }
  }
}

"== 产物"
Get-ChildItem "$ROOT\models\9b\gguf" -Filter 'kittyrev9b-nsfw-*' -ErrorAction SilentlyContinue |
  Select-Object Name, @{n='GB';e={[math]::Round($_.Length/1GB,2)}} | Format-Table -AutoSize
