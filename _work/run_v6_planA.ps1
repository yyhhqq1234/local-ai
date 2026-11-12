# 2B 门控 v6 纠偏训练（方案 A：清洗数据后重训）
#
# 【为什么有 v6】2026-11-05 评测 v5-b13/final：recall 0.4667 / leak 0.0 / fpr 0.0625 / trap 0.0
#   逐条排查发现 recall 天花板不在训练，在**训练数据本身**：
#     v5 许可组 19,068 条里只有 59.73% 能过 55 词严格判据（hits≥2）
#     35.75% 的许可回复 hits=0（文学化暗示 / 心理描写 / 短对白）
#   → 模型 100% 复刻数据也只能到 59.73%，GateRecall ≥0.90 数学上不可达
#
# 【v6 做了什么】_work/build_gate_v6.py --min-hits 3 --apply
#   许可组只留 hits≥3 的 10,483 条（p10=4 p50=8 p90=13，hits≥2 比例 100.00%）
#   常规组 5,902 条全留（该拒的能力来源，含 hits≥2 比例 2.41%，正常）
#   合计 16,385 行 = 4,096 步 / epoch
#   留 1 个词余量（min_hits=3 而非 2），防止模型学到"刚好压线"
#
# 【起点为什么用 v5-b13/final 而不是 v5-s1/final】
#   v5-b13 已有当前最强判别能力（leak 0 / trap 0 / fpr 1/16），只是"写不够露骨"
#   → 从它起做纠偏，只动"写"这一维，不重学"拒"
#   → lr 必须中低（8e-6 → 5e-7），高 lr 会把 leak/fpr 打崩
#
# 【蓝屏/碎片对策】沿用 A-v2 已验证三件套（实测 reserved 8.0–9.04 GiB，旧配置 10.23）
#   --optim paged_adamw_8bit · VRAM_FRAC 0.88 · max_split_size_mb 64
#   · gc_threshold 0.85 · 每 50 步 empty_cache · 每段 400 步 · 段间冷却 600s
#
# 用法：pwsh -NoProfile -File _work/run_v6_planA.ps1 [-Probe] [-StartSeg N]

param(
    [switch]$Probe,
    [int]$MaxSeg = 12,
    [int]$StepsPerSeg = 400,
    [int]$CooldownSec = 600,
    [int]$SkipStart = 0,
    [int]$StartSeg = 2
)

$ErrorActionPreference = "Continue"
$root = "D:\BaiduNetdiskDownload\Local-AI"
Set-Location $root

$py        = Join-Path $root "train\.venv\Scripts\python.exe"
$data      = "train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated-v6.jsonl"
$base      = "train\lines\9b-oxcoder\models\OxCoder-9B"
$startInit = "train\lines\9b-oxcoder\out\v5-b13\final"     # 最强判别能力起点（7200 等效步）
$segLog    = Join-Path $root "train\logs\v6-planA.log"

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

# 纠偏专用低 lr：11 段从 8e-6 余弦退到 5e-7（v5 用的是 1.3e-5 起，太高会毁判别能力）
$lrs = @("8e-6","7.8e-6","7.4e-6","6.8e-6","6e-6","5.1e-6","4.1e-6","3e-6","2e-6","1.1e-6","5e-7")

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Output $line
    Add-Content -Path $segLog -Value $line -Encoding UTF8
}

# ── 环境：低负载 + 抗碎片 ──────────────────────────────────
$env:PYTORCH_CUDA_ALLOC_CONF = "max_split_size_mb:64,garbage_collection_threshold:0.85"
$env:PYTORCH_ALLOC_CONF      = $env:PYTORCH_CUDA_ALLOC_CONF
$env:MEM_EMPTY_EVERY      = "50"
$env:VRAM_FRAC            = "0.88"
$env:PYTHONIOENCODING     = "utf-8"
$env:HF_HUB_OFFLINE       = "1"
$env:OMP_NUM_THREADS      = "6"
$env:MKL_NUM_THREADS      = "6"

if (-not (Test-Path (Join-Path $root $startInit))) { Log "★ 起点不存在：$startInit → 中止"; exit 1 }
if (-not (Test-Path (Join-Path $root $data)))      { Log "★ 数据不存在：$data → 中止"; exit 1 }

# ── 探针：20 步验证 v6 数据 + 显存 ─────────────────────────
if ($Probe) {
    $pOut = "train\lines\9b-oxcoder\out\_probeC"
    $pLog = Join-Path $root "train\logs\probeC.log"
    if (Test-Path (Join-Path $root $pOut)) { Remove-Item (Join-Path $root $pOut) -Recurse -Force -ErrorAction SilentlyContinue }
    Log "================ 探针C 20 步（v6 数据 · 起点 v5-b13）================"
    GpuSnap "before"
    $a1 = @(
        "-u","train\lines\_shared\scripts\train_qlora9b.py",
        "--base",$base, "--data",$data, "--stage","nsfw",
        "--init-adapter",$startInit, "--out",$pOut,
        "--ctx","2048","--epochs","1","--lr","8e-6","--ga","4","--bs","1","--seed","42",
        "--lora-r","32","--lora-alpha","64","--lora-dropout","0.1","--weight-decay","0.01",
        "--optim","paged_adamw_8bit","--use-liger-ce",
        "--skip-samples","0",
        "--max-steps","20","--save-steps","20","--save-total-limit","1"
    )
    $p = Start-Process -FilePath $py -ArgumentList $a1 -WorkingDirectory $root `
         -WindowStyle Hidden -RedirectStandardOutput $pLog -RedirectStandardError "$pLog.err" -PassThru
    Log "   python PID=$($p.Id) · 日志 $pLog"
    $t0 = Get-Date
    while (-not $p.HasExited -and ((Get-Date) - $t0).TotalSeconds -lt 900) {
        Start-Sleep -Seconds 30
        $tail = if (Test-Path $pLog) { (Get-Content $pLog -Tail 1 -ErrorAction SilentlyContinue) } else { "" }
        Log "   probeC: $tail"
    }
    GpuSnap "after"
    Log "   探针C 退出码=$($p.ExitCode) 耗时=$([int]((Get-Date)-$t0).TotalSeconds)s"
    if (Test-Path $pLog) {
        $hit = Select-String -Path $pLog -Pattern '剩余|全量' | Select-Object -First 1
        Log "   数据行确认：$($hit.Line)"
    }
    Log "================ 探针C 结束 ================"
    exit 0
}

# ── 正式分段 ────────────────────────────────────────────────
$segLast = [Math]::Min($MaxSeg, $lrs.Count + 1)
$segCount = $segLast - $StartSeg + 1
Log "================ v6 纠偏训练启动（min_hits=3 清洗版）================"
Log "数据 $data（16,385 行 · 许可 10,483 全 hits≥3 · 常规 5,902）"
Log "起点 $startInit（v5-b13/final，等效 7200 步，最强判别能力）"
Log "段 $StartSeg→$segLast · 每段 $StepsPerSeg 步 · 冷却 ${CooldownSec}s · skip 起点 $SkipStart"
Log "lr 序列：$($lrs -join ', ')（纠偏低 lr，保护 leak/fpr）"
Log "低负载：paged_adamw_8bit · VRAM_FRAC 0.88 · ctx 2048 · max_split_size_mb 64 · gc 0.85 · empty_cache/50步"

if ($StartSeg -le 2) {
    $prevFinal = $startInit
} else {
    $prevFinal = "train\lines\9b-oxcoder\out\v6-c$($StartSeg - 1)\final"
    if (-not (Test-Path (Join-Path $root $prevFinal))) {
        Log "★ 起始段需要上一段 final：$prevFinal 不存在 → 中止"; exit 1
    }
    Log "起始段 $StartSeg 的起点：$prevFinal"
}

for ($i = 0; $i -lt $segCount; $i++) {
    $seg    = $i + $StartSeg
    $segOut = "train\lines\9b-oxcoder\out\v6-c$seg"
    $logOut = Join-Path $root "train\logs\v6-c$seg-train.log"
    $skip   = $SkipStart + ($seg - 2) * $StepsPerSeg * 4
    $lrIdx  = [Math]::Max(0, [Math]::Min($seg - 2, $lrs.Count - 1))

    if (-not (Test-Path (Join-Path $root $prevFinal))) { Log "★ 起点不存在：$prevFinal → 中止"; break }

    GpuSnap "c$seg-before"
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

    while (-not $p.HasExited) {
        Start-Sleep -Seconds 60
        if ($p.HasExited) { break }
        $tl = if (Test-Path $logOut) { (Get-Content $logOut -Tail 1 -ErrorAction SilentlyContinue) } else { "" }
        Log "   c$seg t=$([int]((Get-Date)-$t0).TotalSeconds)s | $tl"
        GpuSnap "c$seg-t$([int]((Get-Date)-$t0).TotalSeconds)"
        if (((Get-Date) - $t0).TotalSeconds -gt 5400) {
            Log "   ★ 第 $seg 段超过 90 min → 强制终止（中间 checkpoint 每 100 步落盘）"
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
        if ($sz -gt 300000000) { Log "   ★ adapter >300MB（双层 LoRA）→ 本段作废" }
        elseif ($sz -lt 100000000) { Log "   ★ adapter <100MB（异常小）→ 本段作废" }
        else { $prevFinal = "$segOut\final" }
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
                $prevFinal = "train\lines\9b-oxcoder\out\v6-c$seg\$($ckpts[-1].Name)"
                Log "   → 用该 checkpoint 作为下一段起点"
            }
        }
    }

    if (Test-Path $logOut) {
        $bad = Select-String -Path $logOut -Pattern '\bnan\b|\binf\b|Traceback|CUDA out of memory|OutOfMemoryError' -ErrorAction SilentlyContinue |
               Select-Object -First 3
        if ($bad) { Log "   ★ 日志异常命中："; $bad | ForEach-Object { Log "      $($_.Line.Trim())" } }
        else { Log "   日志体检：无 NaN/Inf/Traceback/OOM" }
    }

    GpuSnap "c$seg-after"
    if ($i -lt ($segCount - 1)) {
        Log "   冷却 ${CooldownSec}s ..."
        Start-Sleep -Seconds $CooldownSec
    }
}

Log "================ v6 纠偏训练结束 ================"
Log "最终可用 adapter：$prevFinal"
