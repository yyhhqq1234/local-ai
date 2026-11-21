# GGUF 服务能力基准：上下文上限 + 输出速度（tok/s）
# 用法: pwsh -File _work\quant\bench_ctx.ps1 -Model models\9b\gguf\xxx.gguf [-Port 8095]
param(
  [string]$Model = 'models\9b\gguf\kittyrev9b-b1-Q5_K_M-imx.gguf',
  [int]$Port = 8095,
  [string]$Bin = 'engines\llama-cpp\llama-bin'
)
$ROOT = 'D:\BaiduNetdiskDownload\Local-AI'
Set-Location $ROOT
$exe = "$ROOT\$Bin\llama-server.exe"
$results = @()

function Bench([string]$tag, [int]$ctx, [string]$ctk, [string]$ctv, [int]$nPredict = 128) {
  $log = "$ROOT\_work\quant\bench-$tag.log"
  $args = @('-m', $Model, '--port', $Port, '-c', "$ctx", '-ngl', '99', '-fa', 'on',
            '--jinja', '--reasoning-format', 'none', '--no-warmup')
  if ($ctk) { $args += @('-ctk', $ctk) }
  if ($ctv) { $args += @('-ctv', $ctv) }
  $p = Start-Process -FilePath $exe -ArgumentList $args -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden -PassThru
  $ready = $false
  for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Seconds 2
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 3; $ready = $true; break } catch { }
  }
  if (-not $ready) {
    "  [$tag] 启动失败（见 $log.err）"
    if (Test-Path "$log.err") { (Get-Content "$log.err" -Tail 3) -join ' | ' }
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ tag = $tag; ctx = $ctx; kv = "$ctk/$ctv"; ok = $false; tps = $null }
  }
  $body = @{ model = $Model; messages = @(@{ role = 'user'; content = '用 200 字说明什么是进程注入。' });
             max_tokens = $nPredict; temperature = 0.3; stream = $false } | ConvertTo-Json -Depth 5
  $sw = [Diagnostics.Stopwatch]::StartNew()
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/chat/completions" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 600
    $sw.Stop()
    $ct = [int]$r.usage.completion_tokens
    $tps = [math]::Round($ct / $sw.Elapsed.TotalSeconds, 1)
    $vram = (& 'C:\ProgramData\anaconda3\python.exe' -c "import subprocess;print(subprocess.run(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader'],capture_output=True,text=True).stdout.strip())")
    "  [$tag] ctx=$ctx kv=$ctk/$ctv  tok/s=$tps  tokens=$ct  vram=$vram"
    $results += [pscustomobject]@{ tag = $tag; ctx = $ctx; kv = "$ctk/$ctv"; ok = $true; tps = $tps; vram = $vram }
  } catch {
    "  [$tag] 请求失败: $($_.Exception.Message)"
    $results += [pscustomobject]@{ tag = $tag; ctx = $ctx; kv = "$ctk/$ctv"; ok = $false; tps = $null }
  }
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 4
}

"== 基准: $Model"
Bench 'ctx64k-q4kv'  65536 'q4_0' 'q4_0' 128
Bench 'ctx128k-q4kv' 131072 'q4_0' 'q4_0' 128
Bench 'ctx256k-q4kv' 262144 'q4_0' 'q4_0' 128
Bench 'ctx32k-q4kv'  32768 'q4_0' 'q4_0' 128

"== 汇总"
$results | Format-Table -AutoSize
$results | ConvertTo-Json -Depth 4 | Set-Content "$ROOT\_work\quant\bench-result.json" -Encoding UTF8
"结果已写 _work\quant\bench-result.json"

