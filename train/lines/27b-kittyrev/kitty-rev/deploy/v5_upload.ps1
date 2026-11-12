# v5_upload.ps1 —— 开机后第一件事：把 V5 新增/改动的文件推上云端
# 用法：pwsh -NoProfile -File deploy\v5_upload.ps1
# 幂等：已存在且大小一致的跳过

$ErrorActionPreference = 'Stop'
$Repo = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev'
$R    = '/root/autodl-tmp/kitty-rev'
$env:AUTODL_HOST = if ($env:AUTODL_HOST) { $env:AUTODL_HOST } else { '123.127.15.155' }
$Py = 'C:\ProgramData\anaconda3\python.exe'

function Put($local, $remote) {
    if (-not (Test-Path $local)) { Write-Host "  [SKIP] 本地缺 $local"; return }
    $sz = (Get-Item $local).Length
    Write-Host ("  [PUT] {0}  ({1:N0} B) -> {2}" -f (Split-Path $local -Leaf), $sz, $remote)
    & $Py "$Repo\deploy\remote.py" --put $local $remote 2>&1 | Select-Object -Last 2
}

Write-Host "===== V5 上传清单 ====="

# 1 训练数据（必须）
Put "$Repo\data\intent3\v5-mix\train.jsonl"  "$R/data/intent3/v5-mix/train.jsonl"
Put "$Repo\data\intent3\v5-mix\manifest.json" "$R/data/intent3/v5-mix/manifest.json"

# 2 编排与量化链（必须）
Put "$Repo\tools\v5_auto.py"      "$R/tools/v5_auto.py"
Put "$Repo\tools\chain_repair.py" "$R/tools/chain_repair.py"

# 3 方案与模板（参考，出问题时可查）
Put "$Repo\logs\v5\TEAM-PLAN-V5.md"  "$R/logs/v5/TEAM-PLAN-V5.md"
Put "$Repo\logs\v5\PR-TEMPLATE.md"   "$R/logs/v5/PR-TEMPLATE.md"

# 4 校验脚本（本地已验，云端再验一次语法）
Put "$Repo\tools\check_v5_auto.py" "$R/tools/check_v5_auto.py"

Write-Host "`n===== 云端自检 ====="
& $Py "$Repo\deploy\remote.py" --cmd @'
R=/root/autodl-tmp/kitty-rev
echo "--- 文件就位 ---"
for f in data/intent3/v5-mix/train.jsonl tools/v5_auto.py tools/chain_repair.py tools/check_v5_auto.py; do
  if [ -f "$R/$f" ]; then echo "  OK  $f  $(stat -c%s $R/$f) B"; else echo "  MISS $f"; fi
done
echo "--- 训练集行数 ---"
wc -l < "$R/data/intent3/v5-mix/train.jsonl" 2>/dev/null
echo "--- python 语法 ---"
/root/miniconda3/bin/python -m py_compile "$R/tools/v5_auto.py" && echo "  v5_auto.py OK"
/root/miniconda3/bin/python -m py_compile "$R/tools/chain_repair.py" && echo "  chain_repair.py OK"
echo "--- 静态核对 ---"
cd "$R" && /root/miniconda3/bin/python tools/check_v5_auto.py 2>&1 | tail -14
echo "--- mmproj 转换器在不在 ---"
ls -l /root/autodl-tmp/lc/convert_hf_to_gguf.py "$R/ninfer-all-master/convert_hf_to_gguf.py" 2>/dev/null || echo "  两处都没有，S3 会停（需先确认 llama.cpp 源码位置）"
echo "--- 磁盘 ---"
df -h /root/autodl-tmp | tail -1
'@ 2>&1
