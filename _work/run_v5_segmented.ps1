# 2B 门控 v5 分段训练（方案 A）
# 背景：系统 3 次蓝屏 0x116 (VIDEO_TDR)，长时间满载必然触发
# 策略：每段 800 步（约 70 min）→ 退出 → 冷却 5 min → 从上一段 final 用 --init-adapter 续
#      每段独立目录（避免 checkpoint 同名覆盖），崩溃也不丢已完成的段
# 用法：powershell -NoProfile -File _work/run_v5_segmented.ps1

$ErrorActionPreference = "Continue"
$root = "D:\BaiduNetdiskDownload\Local-AI"
Set-Location $root

$py      = Join-Path $root "train\.venv\Scripts\python.exe"
$data    = "train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated-v5.jsonl"
$base    = "train\lines\9b-oxcoder\models\OxCoder-9B"
$firstInit = "train\lines\9b-oxcoder\out\2b-nsfw-v5\checkpoint-1600"   # 最后一个 173MB 单层干净点
$stepsPerSeg = 800
$cooldownSec = 300
# lr 手动余弦：从起点 1600 步已训，按剩余进度递减
$lrs = @("1.2e-5", "1.1e-5", "9e-6", "7e-6", "5e-6", "3e-6", "2e-6")
$segLog = Join-Path $root "train\logs\v5-segmented.log"

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Output $line
    Add-Content -Path $segLog -Value $line -Encoding UTF8
}

$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"
$env:VRAM_FRAC = "0.93"
$env:PYTHONIOENCODING = "utf-8"
$env:HF_HUB_OFFLINE = "1"
$env:OMP_NUM_THREADS = "6"
$env:MKL_NUM_THREADS = "6"

Log "================ 分段训练启动（方案 A，每段 $stepsPerSeg 步）================"
Log "起点 $firstInit · 段间冷却 ${cooldownSec}s · lr 序列 $($lrs -join ', ')"

$prevFinal = $null
for ($i = 0; $i -lt $lrs.Count; $i++) {
    $seg = $i + 1
    $segOut = "train\lines\9b-oxcoder\out\v5-s$seg"

    # 起点：第一段用 ckpt-1600，之后用上一段的 final
    $init = if ($prevFinal) { $prevFinal } else { $firstInit }
    if (-not (Test-Path (Join-Path $root $init))) {
        Log "★ 起点不存在：$init → 中止"
        break
    }
    # 上一段如果真的失败了，退回它之前的 final（沿用更早的落点）
    $logOut = Join-Path $root "train\logs\v5-s$seg-train.log"

    Log "---- 第 $seg 段开始：init=$init · out=$segOut · lr=$($lrs[$i]) · $stepsPerSeg 步 ----"

    $argList = @(
        "-u", "train\lines\_shared\scripts\train_qlora9b.py",
        "--base", $base,
        "--data", $data,
        "--stage", "nsfw",
        "--init-adapter", $init,
        "--out", $segOut,
        "--ctx", "2048", "--epochs", "1", "--lr", $lrs[$i], "--ga", "4", "--bs", "1", "--seed", "42",
        "--lora-r", "32", "--lora-alpha", "64", "--lora-dropout", "0.1", "--weight-decay", "0.01",
        "--optim", "adamw_torch", "--use-liger-ce",
        "--max-steps", "$stepsPerSeg",
        "--save-steps", "400", "--save-total-limit", "4"
    )

    $p = Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $root `
         -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError "$logOut.err" -PassThru -ErrorAction SilentlyContinue
    if ($p) {
        Log "   python PID=$($p.Id) 已启动"
        $p | Wait-Process -Timeout 10800 -ErrorAction SilentlyContinue
    } else {
        Log "★ 第 $seg 段 python 启动失败（检查 $logOut.err）"
    }

    $finalPath = Join-Path $root "$segOut\final"
    if (Test-Path $finalPath) {
        $ad = Join-Path $finalPath "adapter_model.safetensors"
        $sz = if (Test-Path $ad) { (Get-Item $ad).Length } else { 0 }
        Log ("   OK 第 $seg 段完成 · adapter={0:N0} B" -f $sz)
        if ($sz -gt 300000000) {
            Log "   ★ adapter 超过 300MB（双层 LoRA 迹象），本段作废，不用于续训"
        } else {
            $prevFinal = $segOut + "\final"
        }
    } else {
        Log "   ★ 第 $seg 段未产出 final（可能被蓝屏/异常打断）→ 下一段沿用上一个有效起点"
    }

    if ($seg -lt $lrs.Count) {
        Log "   冷却 ${cooldownSec}s ..."
        Start-Sleep -Seconds $cooldownSec
    }
}

Log "================ 分段训练结束 ================"
Log "最终可用 adapter：$prevFinal"
