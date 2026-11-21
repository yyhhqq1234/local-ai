# B1 训练启动：OxCoder-9B 基座 + kitty 逆向能力 + NSFW 能力（QLoRA）
# 用法: pwsh -File _work\rebuild\train_b1.ps1 [-Epochs 3] [-MaxSteps -1]
param([double]$Epochs = 3.0, [int]$MaxSteps = -1, [int]$Ctx = 2048, [int]$Ga = 16, [double]$Lr = 5e-5, [int]$LoraR = 64)
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$PY = "$ROOT\train\.venv\Scripts\python.exe"
$BASE = "$ROOT\train\lines\9b-oxcoder\models\OxCoder-9B"
$DATA = "$ROOT\train\lines\9b-oxcoder\data\b1-combined\train-b1.jsonl"
$OUT = "$ROOT\train\lines\9b-oxcoder\out\b1-oxcoder-nsfw-kitty"
$LOG = "$ROOT\train\logs\b1-train-$(Get-Date -Format yyyyMMdd-HHmm).log"
New-Item -ItemType Directory -Force -Path "$ROOT\train\logs" | Out-Null

if (-not (Test-Path "$BASE\config.json")) { throw "缺基座元数据: $BASE" }
$w = Get-Item "$BASE\model.safetensors" -ErrorAction SilentlyContinue
if (-not $w -or $w.Length -lt 15GB) { throw ("基座权重未下完: {0:N2} GB" -f (($w.Length)/1GB)) }
if (-not (Test-Path $DATA)) { throw "缺数据集: $DATA" }

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTORCH_CUDA_ALLOC_CONF = 'expandable_segments:True'
& $PY "$ROOT\train\lines\_shared\scripts\train_qlora.py" `
  --base $BASE --data $DATA --out $OUT `
  --ctx $Ctx --epochs $Epochs --max-steps $MaxSteps --bs 1 --ga $Ga --lr $Lr `
  --lora-r $LoraR --lora-alpha ($LoraR * 2) 2>&1 | Tee-Object -FilePath $LOG
"LOG=$LOG"
