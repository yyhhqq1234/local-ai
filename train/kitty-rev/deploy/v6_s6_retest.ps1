# v6_s6_retest.ps1 — V6 复测一键：切 v6 引擎 → 等就绪 → 23 题 × 3 轮 → 与基线对照
#
# 设计要点（都是踩过的坑）：
#   1) 起引擎必须用单字符串 ArgumentList 加内嵌引号 —— 用数组会因路径含横线/空格散架
#   2) READY 判据不能只看进程存在，必须 /v1/models 真回 200
#   3) 复测与基线必须同口径：--rounds 4 --max-tokens 1536 --repeat 3
#   4) 对照的基线是「修好 53 个工具 description 后」的那份，不是旧 schema 的
#
# 用法：
#   & 'C:\Program Files (x86)\PowerShell\7\pwsh.exe' -File v6_s6_retest.ps1 -Model <v6.ninfer 绝对路径>

param(
    [Parameter(Mandatory = $true)][string]$Model,
    [string]$Baseline = "D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev\logs\v6\BASE-ALL23-FIXEDSCHEMA.json",
    [string]$Out      = "D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev\logs\v6\JUDGE-ALL23-V6-VOTED.json",
    [int]$Rounds = 4,
    [int]$MaxTokens = 1536,
    [int]$Repeat = 3,
    [int]$ReadyTimeoutSec = 180
)

$ErrorActionPreference = 'Continue'
$py    = 'C:\ProgramData\anaconda3\python.exe'
$pwsh7 = 'C:\Program Files (x86)\PowerShell\7\pwsh.exe'
$here  = Split-Path -Parent $MyInvocation.MyCommand.Path
$root  = Split-Path -Parent $here
$log   = Join-Path $root "logs\v6\S6-RETEST.log"
$null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log)

function W([string]$m) {
    $line = "$(Get-Date -Format 'HH:mm:ss') $m"
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

W "=== S6 START model=$Model"
if (-not (Test-Path -LiteralPath $Model)) { W "FATAL 模型文件不存在: $Model"; exit 2 }

# ── 1) 停当前引擎 ─────────────────────────────────────────────
Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { W "停引擎 pid=$($_.Id)"; $_ | Stop-Process -Force }
Start-Sleep -Seconds 4

# ── 2) 起 v6 引擎（单字符串参数，防散架）──────────────────────────
$script = Join-Path $here '..\..\ninfer-csunx\run-engine.ps1'
$script = (Resolve-Path $script).Path
$engLog = Join-Path $root "logs\v6\engine-v6-run.log"
$argstr = '-NoLogo -NoProfile -File "{0}" -ModelFile "{1}"' -f $script, $Model
W "起引擎 argstr=$argstr"
Start-Process -FilePath $pwsh7 -ArgumentList $argstr -RedirectStandardOutput $engLog -RedirectStandardError ($engLog + '.err') -WindowStyle Hidden

# ── 3) READY 判据：/v1/models 真回 200 ─────────────────────────
$ready = $false
$t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $ReadyTimeoutSec) {
    Start-Sleep -Seconds 3
    try {
        $r = Invoke-RestMethod 'http://127.0.0.1:1234/v1/models' -TimeoutSec 3
        W "READY after $([int]((Get-Date) - $t0).TotalSeconds)s id=$($r.data[0].id)"
        $ready = $true; break
    } catch { }
}
if (-not $ready) {
    W "FATAL 引擎 ${ReadyTimeoutSec}s 未就绪"
    if (Test-Path $engLog) { Get-Content $engLog -Tail 15 | ForEach-Object { W "  eng| $_" } }
    exit 3
}
W "引擎加载文件："
Get-Content $engLog | Select-String 'model  :' | Select-Object -Last 1 | ForEach-Object { W "  $($_.Line.Trim())" }

# ── 4) 复测（同口径）───────────────────────────────────────────
W "复测开始 rounds=$Rounds max_tokens=$MaxTokens repeat=$Repeat"
Push-Location $root
& $py 'eval\eval_kitty_v6.py' --rounds $Rounds --max-tokens $MaxTokens --repeat $Repeat --out $Out 2>&1 |
    ForEach-Object { Write-Output $_; Add-Content -Path $log -Value $_ -Encoding utf8 }
$rc = $LASTEXITCODE
Pop-Location
W "复测结束 rc=$rc out=$Out"

# ── 5) 与基线对照 ─────────────────────────────────────────────
if ((Test-Path $Out) -and (Test-Path $Baseline)) {
    W "=== 与基线对照 ==="
    & $py -c @"
import json
base = json.load(open(r'$Baseline', encoding='utf-8'))
new  = json.load(open(r'$Out', encoding='utf-8'))
print(f\"{'分类':<22}{'基线':>10}{'v6':>10}{'Δ':>6}\")
cats = sorted(set(base['byCat']) | set(new['byCat']))
for c in cats:
    b = base['byCat'].get(c, {}); n = new['byCat'].get(c, {})
    bs = f\"{b.get('pass',0)}/{b.get('total',0)}\"; ns = f\"{n.get('pass',0)}/{n.get('total',0)}\"
    print(f\"{c:<22}{bs:>10}{ns:>10}{n.get('pass',0)-b.get('pass',0):>+6}\")
print(f\"{'总计':<22}{str(base['pass'])+'/'+str(base['total']):>10}{str(new['pass'])+'/'+str(new['total']):>10}{new['pass']-base['pass']:>+6}\")
print()
for b, n in zip(base['detail'], new['detail']):
    if b.get('pass') != n.get('pass'):
        print(f\"  题{n['i']} [{n['cat']}] {b.get('pass')} -> {n.get('pass')}  {str(n.get('why'))[:70]}\")
"@ | ForEach-Object { W "  $_" }
} else {
    W "WARN 基线或复测产物缺失，跳过对照（基线=$Baseline）"
}

W "=== S6 DONE"
exit 0
