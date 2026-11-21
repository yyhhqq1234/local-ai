# b1v4 长上下文召回：64K + 256K（KV q4_0）
param([int]$Port = 8099)
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$PY = "$ROOT\train\.venv\Scripts\python.exe"
$BIN = "$ROOT\engines\llama-cpp\llama-bin"
$Q6 = "$ROOT\models\9b\gguf\kittyrev9b-b1v4-Q6_K.gguf"
$LOG = "$ROOT\_work\quant\v4-recall.log"

function Srv([int]$ctx) {
  $p = Start-Process -FilePath "$BIN\llama-server.exe" -ArgumentList @('-m', $Q6, '--port', "$Port", '-c', "$ctx",
    '-ctk', 'q4_0', '-ctv', 'q4_0', '-ngl', '99', '-fa', 'on', '--jinja', '--reasoning-format', 'none', '--no-warmup') `
    -RedirectStandardOutput "$ROOT\_work\quant\rc-$ctx.log" -RedirectStandardError "$ROOT\_work\quant\rc-$ctx.err" -WindowStyle Hidden -PassThru
  for ($i = 0; $i -lt 150; $i++) { Start-Sleep -Seconds 2; try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3; return $p } catch { } }
  return $null
}

Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

foreach ($c in 65536, 262144) {
  $s = Srv $c
  if (-not $s) { "[$c] 服务启动失败" | Tee-Object -FilePath $LOG -Append; continue }
  "=== ctx=$c" | Tee-Object -FilePath $LOG -Append
  & $PY "$ROOT\_work\quant\verify_longctx.py" --port $Port --model $Q6 --ctx $c 2>&1 | Tee-Object -FilePath $LOG -Append
  Stop-Process -Id $s.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 5
}
'== recall 完成' | Tee-Object -FilePath $LOG -Append
