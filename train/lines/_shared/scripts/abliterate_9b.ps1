# abliterate_9b.ps1 — 用 Heretic 对 9B 基座做自动去审查
# 用法:
#   .\abliterate_9b.ps1                      # 默认 OxCoder-9B
#   .\abliterate_9b.ps1 -Model <path> -Trials 150
# 说明:
#   · Heretic 全自动：TPE 搜索同时最小化"拒绝数"与"与原模型的 KL 散度"
#   · 12 GB 卡必须开 bnb_4bit，否则权重放不下
#   · study 目录可续跑；中断后加同一 --study 继续
param(
  [string]$Model  = "",
  [int]$Trials    = 100,
  [string]$StudyDir = "",
  [switch]$NoQuant
)

$ErrorActionPreference = "Stop"
$Root = "D:\BaiduNetdiskDownload\Local-AI"
$Here = Join-Path $Root "_repos\heretic"

if ([string]::IsNullOrWhiteSpace($Model)) {
  $Model = Join-Path $Root "train\lines\9b-oxcoder\models\OxCoder-9B"
}
if (-not (Test-Path $Model)) { throw "基座不存在: $Model" }
if (-not (Test-Path $Here))  { throw "heretic 仓库不存在: $Here" }

if ([string]::IsNullOrWhiteSpace($StudyDir)) {
  $StudyDir = Join-Path $Root "train\logs\heretic-oxcoder9b"
}
New-Item -ItemType Directory -Force -Path $StudyDir | Out-Null

Write-Host "=== Heretic abliteration ===" -ForegroundColor Cyan
Write-Host "model  = $Model"
Write-Host "trials = $Trials"
Write-Host "study  = $StudyDir"
Write-Host "quant  = $(if ($NoQuant) { 'none' } else { 'bnb_4bit' })"
Write-Host ""
Write-Host "跑完会进入交互菜单：选 'Save model' 存盘，路径填 train\lines\9b-oxcoder\models\OxCoder-9B-abliterated" -ForegroundColor Yellow
Write-Host ""

Push-Location $Here
try {
  # 优先 uv（仓库带 uv.lock，依赖最稳）；没有则用已装的 heretic
  $hasUv = Get-Command uv -ErrorAction SilentlyContinue
  $quantArg = if ($NoQuant) { @() } else { @("--quantization", "bnb_4bit") }

  if ($hasUv) {
    & uv run heretic $Model --n-trials $Trials --study $StudyDir @quantArg
  } else {
    $heretic = Get-Command heretic -ErrorAction SilentlyContinue
    if (-not $heretic) {
      throw "未找到 heretic 命令。先在本目录执行: uv sync  或  pip install -U heretic-llm"
    }
    & heretic $Model --n-trials $Trials --study $StudyDir @quantArg
  }
} finally {
  Pop-Location
}

Write-Host ""
Write-Host "完成后必做（门禁，不过不许进 SFT）:" -ForegroundColor Cyan
Write-Host "  1) 20 条目标 prompt 抽检：拒绝是否消失"
Write-Host "  2) 5 个真实 issue A/B：SWE 型能力不低于 OxCoder-9B(73.5) - 3pp"
Write-Host "  3) 若明显下滑 → 改用 _repos/abliteration（层范围可控，更保守）"
