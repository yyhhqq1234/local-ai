# 2B 门控 v5 续训 · 方案 A v2（低负载分段 + 数据游标推进）
#
# 【v1 → v2 的致命修正】2026-11-05 01:36 监控子 agent 发现并经实测确认：
#   --init-adapter 只搬 LoRA 权重，不搬 optimizer / scheduler / **数据游标**。
#   每段新建 Trainer + 固定 --seed 42 → RandomSampler 序列每段完全相同
#   → v1 的 10 段 400 步会反复训同一批 1600 条（24970 的 6.4%），另外 61% 数据永不参与。
#   铁证：v5-a2 step15 的 epoch = 0.0024028834601521826，与探针 step15 逐位相同。
#   修法：train_qlora9b.py 新增 --skip-samples N，每段按 N = 起点 + i×400×4 递增。
#
# 【数据覆盖现状盘点（v5-s1/final = 等效 2400 步）】
#   2b-nsfw-v5/checkpoint-1600（1600 步）+ v5-s1（单段连续 800 步，epoch 0→0.128）
#   → 保守估计已覆盖 0..6400 条（v5-s1 那 800 步实际是从头重复了 0..3200）
#   → 本轮从 skip=6400 起，12 段 × 400 步 = 4800 步，覆盖 6400..24970 并略进第 2 epoch
#
# 【蓝屏三重对策】（探针实测 reserved 9.43 GiB / free 1.08 GiB，旧配置是 10.7-11.0 / 0.00-0.36）
#   1) --optim paged_adamw_8bit
#   2) VRAM_FRAC=0.88（PyTorch 硬上限 10.75 GiB，超限即 OOM 而非拖垮 Windows TDR）
#   3) 每段 400 步 + 段间冷却 600s + 单段硬上限 90 min
#   仍保留 ctx=2048（不降！p99 样本 3304 字符≈2100 token，降 ctx 会砍长文尾巴 = 砍掉要练的能力）
#
# 用法：pwsh -NoProfile -File _work/run_v5_planA.ps1 [-Probe] [-MaxSeg 12]

param(
    [switch]$Probe,
    [int]$MaxSeg = 13,
    [int]$StepsPerSeg = 400,
    [int]$CooldownSec = 600,
    [int]$SkipStart = 6400,
    [int]$StartSeg = 2
)

$ErrorActionPreference = "Continue"
$root = "D:\BaiduNetdiskDownload\Local-AI"
Set-Location $root

$py        = Join-Path $root "train\.venv\Scripts\python.exe"
$data      = "train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated-v5.jsonl"
$base      = "train\lines\9b-oxcoder\models\OxCoder-9B"
$startInit = "train\lines\9b-oxcoder\out\v5-s1\final"     # 等效 2400 步干净单层 173 MB
$segLog    = Join-Path $root "train\logs\v5-planA.log"

# pwsh 在本机是 32 位进程 → System32 被 WOW64 重定向到 SysWOW64（无 nvidia-smi）
# 必须走 Sysnative 才能命中真实 64 位 System32
$nvsmi = @(
    (Join-Path $env:SystemRoot "Sysnative\nvidia-smi.exe"),
    "C:\Windows\Sysnative\nvidia-smi.exe",
    (Join-Path $env:SystemRoot "System32\nvidia-smi.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1

function GpuSnap($tag) {
    if (-not $nvsmi) { Log "   [GPU:$tag] (nvidia-smi 不可用)"; return }
    try {
        $r = & $nvsmi --query-gpu=memory.used,memory.free,utilization.gpu,temperature.gpu --format=csv,noheader 2>$null
        Log "   [GPU:$tag] $r"
    } catch { Log "   [GPU:$tag] (查询失败)" }
}

# 手动余弦，12 段（等效步数 2400 → 6400）
$lrs = @("1.3e-5","1.2e-5","1.1e-5","9.5e-6","8.5e-6","7e-6","5.5e-6","4e-6","2.8e-6","1.8e-6","1.1e-6","7e-7")

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Output $line
    Add-Content -Path $segLog -Value $line -Encoding UTF8
}

# ── 环境：低负载 + 抗碎片 ──────────────────────────────────
# 2026-11-05 02:39 实测：b3 reserved 爬到 10.227 GiB（b2 才 9.99），而 peak 只有 8.835
#   → 1.39 GiB 是碎片，不是真实需求。Windows 不支持 expandable_segments，
#     必须靠 max_split_size_mb 切小 + garbage_collection_threshold 主动回收 + 每 50 步 empty_cache
$env:PYTORCH_CUDA_ALLOC_CONF = "max_split_size_mb:64,garbage_collection_threshold:0.85"
$env:PYTORCH_ALLOC_CONF      = $env:PYTORCH_CUDA_ALLOC_CONF
$env:MEM_EMPTY_EVERY      = "50"        # train_qlora9b.py 每 N 步 torch.cuda.empty_cache()
$env:VRAM_FRAC            = "0.88"
$env:PYTHONIOENCODING     = "utf-8"
$env:HF_HUB_OFFLINE       = "1"
$env:OMP_NUM_THREADS      = "6"
$env:MKL_NUM_THREADS      = "6"

if (-not (Test-Path (Join-Path $root $startInit))) {
    Log "★ 起点不存在：$startInit → 中止"; exit 1
}

# ── 探针：验证 --skip-samples 生效 + 20 步显存 ──────────────
if ($Probe) {
    $pOut = "train\lines\9b-oxcoder\out\_probeB"
    $pLog = Join-Path $root "train\logs\probeB.log"
    if (Test-Path (Join-Path $root $pOut)) { Remove-Item (Join-Path $root $pOut) -Recurse -Force -ErrorAction SilentlyContinue }
    Log "================ 探针B 20 步（skip-samples=$SkipStart 验证数据游标）================"
    GpuSnap "before"
    $a1 = @(
        "-u","train\lines\_shared\scripts\train_qlora9b.py",
        "--base",$base, "--data",$data, "--stage","nsfw",
        "--init-adapter",$startInit, "--out",$pOut,
        "--ctx","2048","--epochs","1","--lr","1.3e-5","--ga","4","--bs","1","--seed","42",
        "--lora-r","32","--lora-alpha","64","--lora-dropout","0.1","--weight-decay","0.01",
        "--optim","paged_adamw_8bit","--use-liger-ce",
        "--skip-samples","$SkipStart",
        "--max-steps","20","--save-steps","20","--save-total-limit","1"
    )
    $p = Start-Process -FilePath $py -ArgumentList $a1 -WorkingDirectory $root `
         -WindowStyle Hidden -RedirectStandardOutput $pLog -RedirectStandardError "$pLog.err" -PassThru
    Log "   python PID=$($p.Id) · 日志 $pLog"
    $t0 = Get-Date
    while (-not $p.HasExited -and ((Get-Date) - $t0).TotalSeconds -lt 900) {
        Start-Sleep -Seconds 30
        $tail = if (Test-Path $pLog) { (Get-Content $pLog -Tail 1 -ErrorAction SilentlyContinue) } else { "" }
        Log "   probeB: $tail"
    }
    GpuSnap "after"
    Log "   探针B 退出码=$($p.ExitCode) 耗时=$([int]((Get-Date)-$t0).TotalSeconds)s"
    if (Test-Path $pLog) {
        $hit = Select-String -Path $pLog -Pattern 'skip_samples' | Select-Object -First 1
        Log "   游标验证行：$($hit.Line)"
        $last = Select-String -Path $pLog -Pattern '"epoch"' | Select-Object -Last 1
        Log "   末步 epoch：$($last.Line)"
    }
    Log "================ 探针B 结束 ================"
    exit 0
}

# ── 正式分段 ────────────────────────────────────────────────
$segLast = [Math]::Min($MaxSeg, 13)                        # 段号上限（lrs 索引 = seg-2）
$segCount = $segLast - $StartSeg + 1
Log "================ 方案 A v2 续训启动（数据游标推进版）================"
Log "起点段 $StartSeg → 末段 $segLast · skip 起点 $SkipStart · 每段 $StepsPerSeg 步 · 冷却 ${CooldownSec}s"
Log "低负载：paged_adamw_8bit · VRAM_FRAC 0.88 · ctx 2048 · max_split_size_mb 64 · gc_threshold 0.85 · empty_cache 每 50 步"
Log "数据推进：第 seg 段 skip = $SkipStart + (seg-2)×$($StepsPerSeg*4)（每段吃 $($StepsPerSeg*4) 条新样本）"

# 起点：StartSeg=2 → v5-s1/final；>2 → 上一段 final
if ($StartSeg -le 2) {
    $prevFinal = $startInit
} else {
    $prevFinal = "train\lines\9b-oxcoder\out\v5-b$($StartSeg - 1)\final"
    if (-not (Test-Path (Join-Path $root $prevFinal))) {
        Log "★ 起始段需要上一段 final：$prevFinal 不存在 → 中止"; exit 1
    }
    Log "起始段 $StartSeg 的起点：$prevFinal"
}

for ($i = 0; $i -lt $segCount; $i++) {
    $seg    = $i + $StartSeg
    $segOut = "train\lines\9b-oxcoder\out\v5-b$seg"
    $logOut = Join-Path $root "train\logs\v5-b$seg-train.log"
    $skip   = $SkipStart + ($seg - 2) * $StepsPerSeg * 4
    $lrIdx  = $seg - 2
    if ($lrIdx -lt 0) { $lrIdx = 0 }
    if ($lrIdx -ge $lrs.Count) { $lrIdx = $lrs.Count - 1 }

    if (-not (Test-Path (Join-Path $root $prevFinal))) { Log "★ 起点不存在：$prevFinal → 中止"; break }

    GpuSnap "b$seg-before"
    Log "---- 第 $seg 段：init=$prevFinal · out=$segOut · lr=$($lrs[$lrIdx]) · skip=$skip · $StepsPerSeg 步 · 吃 $skip..$($skip+$StepsPerSeg*4) 条 ----"

    $a = @(
        "-u","train\lines\_shared\scripts\train_qlora9b.py",
        "--base",$base, "--data",$data, "--stage","nsfw",
        "--init-adapter",$prevFinal, "--out",$segOut,
        "--ctx","2048","--epochs","1","--lr",$lrs[$lrIdx],"--ga","4","--bs","1","--seed","42",
        "--lora-r","32","--lora-alpha","64","--lora-dropout","0.1","--weight-decay","0.01",
        "--optim","paged_adamw_8bit","--use-liger-ce",
        "--skip-samples","$skip",
        "--max-steps","$StepsPerSeg","--save-steps","100","--save-total-limit","2"
    )
    $t0 = Get-Date
    $p = Start-Process -FilePath $py -ArgumentList $a -WorkingDirectory $root `
         -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError "$logOut.err" -PassThru
    if (-not $p) { Log "★ 第 $seg 段启动失败"; break }
    Log "   python PID=$($p.Id) · 日志 $logOut"

    # 段内监控：每 60s 落一行
    while (-not $p.HasExited) {
        Start-Sleep -Seconds 60
        if ($p.HasExited) { break }
        $tl = if (Test-Path $logOut) { (Get-Content $logOut -Tail 1 -ErrorAction SilentlyContinue) } else { "" }
        Log "   b$seg t=$([int]((Get-Date)-$t0).TotalSeconds)s | $tl"
        GpuSnap "b$seg-t$([int]((Get-Date)-$t0).TotalSeconds)"
        if (((Get-Date) - $t0).TotalSeconds -gt 5400) {
            Log "   ★ 第 $seg 段超过 90 min → 强制终止（中间 checkpoint 每 100 步已落盘）"
            try { $p.Kill() } catch {}
            break
        }
    }

    $rc = -1
    try { $rc = $p.ExitCode } catch { $rc = -999 }
    $finalPath = Join-Path $root "$segOut\final"
    if (Test-Path $finalPath) {
        $ad = Join-Path $finalPath "adapter_model.safetensors"
        $sz = if (Test-Path $ad) { (Get-Item $ad).Length } else { 0 }
        Log ("   OK 第 {0} 段完成 rc={1} · adapter={2:N0} B · 耗时 {3}s" -f $seg, $rc, $sz, [int]((Get-Date)-$t0).TotalSeconds)
        if ($sz -gt 300000000) {
            Log "   ★ adapter >300MB（双层 LoRA）→ 本段作废"
        } elseif ($sz -lt 100000000) {
            Log "   ★ adapter <100MB（异常小）→ 本段作废"
        } else {
            $prevFinal = "$segOut\final"
        }
    } else {
        Log "   ★ 第 $seg 段无 final（rc=$rc）→ 尝试用段内最后 checkpoint 续"
        $ckpts = Get-ChildItem (Join-Path $root $segOut) -Directory -Filter "checkpoint-*" -ErrorAction SilentlyContinue |
                 Sort-Object { [int]($_.Name -replace 'checkpoint-','') }
        if ($ckpts) {
            $lastCk = $ckpts[-1].FullName
            $ckAd = Join-Path $lastCk "adapter_model.safetensors"
            $ckSz = if (Test-Path $ckAd) { (Get-Item $ckAd).Length } else { 0 }
            Log ("   找到段内 checkpoint：{0} · adapter={1:N0} B" -f $ckpts[-1].Name, $ckSz)
            if ($ckSz -gt 100000000 -and $ckSz -lt 300000000) {
                $prevFinal = "train\lines\9b-oxcoder\out\v5-b$seg\$($ckpts[-1].Name)"
                Log "   → 用该 checkpoint 作为下一段起点"
            }
        }
        Log "   否则沿用上一有效起点 $prevFinal"
    }

    # NaN / OOM 体检（★ 原版用了 -SimpleMatch 把整串当字面量，永不可能命中 → 已修）
    if (Test-Path $logOut) {
        $bad = Select-String -Path $logOut -Pattern '\bnan\b|\binf\b|Traceback|CUDA out of memory|OutOfMemoryError' -ErrorAction SilentlyContinue |
               Select-Object -First 3
        if ($bad) {
            Log "   ★ 日志异常命中："
            $bad | ForEach-Object { Log "      $($_.Line.Trim())" }
        } else {
            Log "   日志体检：无 NaN/Inf/Traceback/OOM"
        }
    }

    GpuSnap "b$seg-after"
    if ($i -lt ($segCount - 1)) {
        Log "   冷却 ${CooldownSec}s ..."
        Start-Sleep -Seconds $CooldownSec
    }
}

Log "================ 方案 A v2 续训结束 ================"
Log "最终可用 adapter：$prevFinal"
