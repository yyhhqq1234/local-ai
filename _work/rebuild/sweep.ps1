# Base + LoRA 运行时缩放扫描：pwsh -File _work\rebuild\sweep.ps1 -Scale 2.0 -Port 8093
param([double]$Scale = 2.0, [int]$Port = 8093)
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$exe = "$ROOT\engines\llama-cpp\llama-bin\llama-server.exe"
$base = "$ROOT\_work\rebuild\base-Q5_K_M.gguf"
$lora = "$ROOT\models\9b\gguf\adapter-2b-nsfw-f16.gguf"
$log = "$ROOT\_work\rebuild\server-$Port.log"
$p = Start-Process -FilePath $exe -ArgumentList @('-m', $base, '--port', "$Port", '-c', '8192', '-ngl', '99',
    '-fa', 'on', '--jinja', '--reasoning-format', 'none', '--no-warmup',
    '--lora-scaled', "$lora`:$Scale") -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden -PassThru
"scale=$Scale port=$Port pid=$($p.Id)"
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Seconds 3
  try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3; "READY after $($i*3)s"; break } catch { }
}
Select-String -Path $log -Pattern 'lora' -SimpleMatch | Select-Object -First 5 | ForEach-Object { $_.Line.Trim() }
$env:PYTHONIOENCODING = 'utf-8'
& 'C:\ProgramData\anaconda3\python.exe' "$ROOT\_work\rebuild\sweep_lora_scale.py" "$Port" 2>&1 | Select-Object -Last 10
Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
