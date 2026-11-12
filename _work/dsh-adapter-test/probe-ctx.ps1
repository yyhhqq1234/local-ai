$exe = 'D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build\apps\ninfer-serve.exe'
$model = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'

function Test-Ctx($ctx, $port, $hostMib) {
  Get-Process ninfer-serve -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force -ErrorAction SilentlyContinue
  Start-Sleep -Milliseconds 900
  $log = "D:\BaiduNetdiskDownload\Local-AI\_tools\ctx-$ctx.log"
  $argv = @($model, '--max-context', "$ctx", '--port', "$port", '--greedy',
            '--host-context-mib', "$hostMib", '--prefill-chunk', '128', '--no-thinking')
  $p = Start-Process -FilePath $exe -ArgumentList $argv -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
  $sw = [Diagnostics.Stopwatch]::StartNew(); $ok = $false
  while ($sw.Elapsed.TotalSeconds -lt 150) {
    Start-Sleep -Milliseconds 500
    if ($p.HasExited) { break }
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -TimeoutSec 2; $ok = $true; break } catch { }
  }
  $cap = (Select-String -Path ($log + '.err') -Pattern 'capacity \|' | Select-Object -Last 1).Line
  if (-not $cap) { $cap = (Select-String -Path $log -Pattern 'capacity \|' | Select-Object -Last 1).Line }
  "ctx=$ctx host=$hostMib ready=$ok in $([int]$sw.Elapsed.TotalSeconds)s pid=$($p.Id)"
  if ($cap) { "   " + $cap.Trim() }
  if (-not $ok -and (Test-Path ($log + '.err'))) { (Get-Content ($log + '.err') -Tail 4) | ForEach-Object { "   ERR " + $_ } }
  return $ok
}

Write-Output '=== 16384 ==='
$r1 = Test-Ctx 16384 1655 2048
if ($r1) {
  $b = @{ model='kittyrev-oxcoder9b-nsfw-gate-full-GSQ'; messages=@(@{role='user';content='说一句话'}); max_tokens=16; temperature=0; stream=$false } | ConvertTo-Json -Depth 6 -Compress
  try { $x = Invoke-RestMethod 'http://127.0.0.1:1655/v1/chat/completions' -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 120; "   对话 OK tok=$($x.usage.completion_tokens)" } catch { "   对话 FAIL " + $_.Exception.Message }
}
Write-Output '=== 32768 ==='
$r2 = Test-Ctx 32768 1656 2048
Write-Output '=== 65536 ==='
$r3 = Test-Ctx 65536 1657 2048
Get-Process ninfer-serve -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Output '=== done ==='
