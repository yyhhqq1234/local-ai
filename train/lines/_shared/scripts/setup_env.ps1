# setup_env.ps1 —— 后训练环境一键建立（全部在根目录内）
# 用法: powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1 [-SkipPython] [-SkipTorch]
param(
    [switch]$SkipPython,
    [switch]$SkipTorch,
    [string]$TorchVersion = "2.11.0",
    [string]$CudaTag      = "cu130"
)
$ErrorActionPreference = "Stop"

# 训练根 = train\ 的父层的 train 目录（脚本所在目录的上一级）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TrainRoot = Split-Path -Parent $ScriptDir
$Venv      = Join-Path $TrainRoot ".venv"
$Py        = Join-Path $Venv "Scripts\python.exe"
$Mirror    = "https://mirrors.aliyun.com/pypi/simple/"

Write-Host "==== 后训练环境建立 ====" -ForegroundColor Cyan
Write-Host "TrainRoot = $TrainRoot"
Write-Host "Venv      = $Venv"

# ---------- 0. 磁盘预检 ----------
$free = [math]::Round((Get-PSDrive D).Free / 1GB, 1)
Write-Host ("[0] D 盘剩余 {0} GB" -f $free)
if ($free -lt 30) { throw "D 盘剩余不足 30 GB，先清理再装" }

# ---------- 1. Python 3.12 ----------
Write-Host "[1] Python 3.12" -ForegroundColor Cyan
$py312 = $null
foreach ($cand in @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:ProgramFiles\Python312\python.exe",
    "C:\Python312\python.exe")) {
    if (Test-Path -LiteralPath $cand) { $py312 = $cand; break }
}
if (-not $py312) {
    $cmd = Get-Command py -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $p = & py -3.12 -c "import sys;print(sys.executable)" 2>$null
            if ($p -and (Test-Path -LiteralPath $p)) { $py312 = $p }
        } catch {}
    }
}
if (-not $py312 -and -not $SkipPython) {
    Write-Host "  未找到 Python 3.12，尝试 winget 安装..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    foreach ($cand in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe")) {
        if (Test-Path -LiteralPath $cand) { $py312 = $cand; break }
    }
}
if (-not $py312) { throw "Python 3.12 未就绪。手工装好后重跑，或加 -SkipPython 并自行保证 py -3.12 可用" }
Write-Host "  python = $py312"
& $py312 -V

# ---------- 2. venv ----------
Write-Host "[2] venv" -ForegroundColor Cyan
if (-not (Test-Path -LiteralPath $Py)) {
    & $py312 -m venv $Venv
    Write-Host "  created $Venv"
} else {
    Write-Host "  exists, reuse"
}
& $Py -V

# ---------- 3. pip 基础 ----------
Write-Host "[3] pip 升级（阿里镜像）" -ForegroundColor Cyan
& $Py -m pip install -U pip setuptools wheel -i $Mirror --quiet
& $Py -m pip --version

# ---------- 4. torch（官方索引，不走 pypi） ----------
if (-not $SkipTorch) {
    Write-Host "[4] torch $TorchVersion+$CudaTag（pytorch 官方索引）" -ForegroundColor Cyan
    & $Py -m pip install "torch==$TorchVersion" --index-url "https://download.pytorch.org/whl/$CudaTag"
    Write-Host "  自检："
    & $Py -c "import torch;print('torch',torch.__version__);print('cuda',torch.version.cuda);print('gpu',torch.cuda.get_device_name(0));print('cap',torch.cuda.get_device_capability(0));print('vram_gb',round(torch.cuda.get_device_properties(0).total_memory/2**30,1))"
    # 判据：cap == (12, 0) 且 vram_gb ≈ 11.9
} else {
    Write-Host "[4] 跳过 torch" -ForegroundColor Yellow
}

# ---------- 5. 训练栈 ----------
Write-Host "[5] 训练栈" -ForegroundColor Cyan
& $Py -m pip install "transformers>=5.8" peft trl accelerate datasets `
    "bitsandbytes==0.50.2" "huggingface_hub[cli]" sentencepiece protobuf safetensors `
    -i $Mirror
& $Py -c "import transformers,peft,trl,accelerate,datasets,bitsandbytes as b;print('transformers',transformers.__version__);print('peft',peft.__version__);print('trl',trl.__version__);print('accelerate',accelerate.__version__);print('bnb',b.__version__)"

# ---------- 6. 环境变量固化（下载/缓存都在根目录内） ----------
Write-Host "[6] 环境变量" -ForegroundColor Cyan
$envFile = Join-Path $TrainRoot "scripts\.env.ps1"
@"
# 每次开新终端先 dot-source 本文件： . .\scripts\.env.ps1
`$env:HF_ENDPOINT = "https://hf-mirror.com"
`$env:HF_HOME     = "$TrainRoot\hf"
`$env:HF_HUB_CACHE = "$TrainRoot\hf\hub"
`$env:TRANSFORMERS_CACHE = "$TrainRoot\hf\transformers"
`$env:HF_HUB_ENABLE_HF_TRANSFER = "0"
`$env:PYTHONUTF8  = "1"
`$env:PYTHONIOENCODING = "utf-8"
`$env:TOKENIZERS_PARALLELISM = "false"
`$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"
"@ | Set-Content -LiteralPath $envFile -Encoding UTF8
Write-Host "  写入 $envFile（开新终端后 dot-source 它）"

# ---------- 7. 目录自检 ----------
Write-Host "[7] 目录自检" -ForegroundColor Cyan
foreach ($d in @("base","data","out","merged","gguf","ninfer","hf","logs","scripts","tmp")) {
    $p = Join-Path $TrainRoot $d
    if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}
Get-ChildItem $TrainRoot -Force | Where-Object { $_.PSIsContainer } | Select-Object -ExpandProperty Name |
    ForEach-Object { "  $_" }

Write-Host ""
Write-Host "==== 完成 ====" -ForegroundColor Green
Write-Host "下一步："
Write-Host "  . .\scripts\.env.ps1"
Write-Host "  & .\.venv\Scripts\python.exe .\scripts\fetch_base.py --size 8b"
Write-Host "  & .\.venv\Scripts\python.exe .\scripts\train_qlora.py --size 8b --max-steps 100"
