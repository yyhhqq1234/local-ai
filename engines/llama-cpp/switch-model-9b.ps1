# 切换 9B 现役模型（带备份 + 回滚提示），默认只 dry-run
param(
  [Parameter(Mandatory = $true)][string]$Model,   # e.g. models\9b\gguf\kittyrev9b-b1v4-Q6_K.gguf
  [switch]$Apply
)
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$gguf = if (Test-Path $Model) { (Resolve-Path $Model).Path } else { Join-Path $ROOT $Model }
if (-not (Test-Path $gguf)) { throw "模型不存在: $gguf" }
$sizeGB = [math]::Round((Get-Item $gguf).Length / 1GB, 2)

$py = "$ROOT\engines\llama-cpp\start-9b.py"
$bat = "$ROOT\engines\llama-cpp\serve.bat"

Write-Host "目标模型: $gguf  ($sizeGB GB)"
Write-Host "将改: $py  与  $bat"

# 读取当前
$curPy = (Select-String -Path $py -Pattern '^\s*MODEL\s*=|"model"\s*:' | Select-Object -First 1).Line
Write-Host "start-9b.py 当前: $curPy"
$curBat = (Select-String -Path $bat -Pattern '^set MODEL=' | Select-Object -First 1).Line
Write-Host "serve.bat  当前: $curBat"

if (-not $Apply) {
  Write-Host ''
  Write-Host '（dry-run）加 -Apply 才写入。写入前会自动备份 .bak-switch-<时间戳>'
  return
}

$ts = Get-Date -Format 'yyyyMMdd-HHmm'
Copy-Item $py "$py.bak-switch-$ts" -Force
Copy-Item $bat "$bat.bak-switch-$ts" -Force

# start-9b.py：替换 MODEL 常量（形如 MODEL = r"...\xxx.gguf" 或 MODEL = "..."）
$s = Get-Content $py -Raw
$rel = $gguf.Substring($ROOT.Length + 1)
# 优先兼容 os.path.join(BASE, "models", "9b", "gguf", "<file>") 形式：只换最后一段
$fname = Split-Path $rel -Leaf
$s2 = [regex]::Replace($s, '(?m)^(\s*MODEL\s*=\s*os\.path\.join\(BASE,\s*"models",\s*"9b",\s*"gguf",\s*)"[^"]*"\)', "`$1`"$fname`")")
if ($s2 -eq $s) { $s2 = [regex]::Replace($s, '(?m)^(\s*MODEL\s*=\s*)(r?"[^"]*")', "`$1r`"$rel`"") }
if ($s2 -eq $s) {
  # 兼容 dict 形式 "model": "..."
  $s2 = [regex]::Replace($s, '("model"\s*:\s*)"[^"]*"', "`$1r`"$rel`"")
}
if ($s2 -eq $s) { Write-Warning 'start-9b.py 未匹配到 MODEL，请手工确认' } else { Set-Content $py $s2 -Encoding UTF8; Write-Host "已改 start-9b.py → $rel" }

# serve.bat：替换 set MODEL=
$b = Get-Content $bat -Raw
$b2 = [regex]::Replace($b, '(?m)^set MODEL=.*$', "set MODEL=$gguf")
if ($b2 -eq $b) { Write-Warning 'serve.bat 未匹配到 set MODEL=' } else { Set-Content $bat $b2 -Encoding UTF8; Write-Host "已改 serve.bat → $gguf" }

Write-Host ''
Write-Host "回滚: Copy-Item '$py.bak-switch-$ts' '$py' -Force; Copy-Item '$bat.bak-switch-$ts' '$bat' -Force"
Write-Host '生效: 重启 DSH（插件 dev_reload_package 会卡死宿主，必须重启）'

