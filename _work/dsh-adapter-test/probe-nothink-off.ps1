$exe = 'D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build\apps\ninfer-serve.exe'
$model = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$port = 1652
$log = 'D:\BaiduNetdiskDownload\Local-AI\_tools\serve-think.log'

Get-Process ninfer-serve -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800

# 关键：不加 --no-thinking
$argv = @($model, '--max-context', '4096', '--port', "$port", '--greedy', '--host-context-mib', '2048', '--prefill-chunk', '128')
$p = Start-Process -FilePath $exe -ArgumentList $argv -PassThru -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
$sw = [Diagnostics.Stopwatch]::StartNew(); $ok = $false
while ($sw.Elapsed.TotalSeconds -lt 120) {
  Start-Sleep -Milliseconds 400
  if ($p.HasExited) { break }
  try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/models" -TimeoutSec 2; $ok = $true; break } catch { }
}
"ready=$ok in $([int]$sw.Elapsed.TotalSeconds)s pid=$($p.Id)"

function TryReq($obj, $tag) {
  $b = $obj | ConvertTo-Json -Depth 8 -Compress
  try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 180
    $c = [string]$r.choices[0].message.content
    $rc = [string]$r.choices[0].message.reasoning_content
    "OK   [$tag] content=$($c.Length) reasoning=$($rc.Length) tok=$($r.usage.completion_tokens) finish=$($r.choices[0].finish_reason)"
    if ($c.Length -gt 0) { "      c: " + $c.Substring(0, [Math]::Min(60, $c.Length)) }
    if ($rc.Length -gt 0) { "      r: " + $rc.Substring(0, [Math]::Min(60, $rc.Length)) }
  } catch {
    $m = $_.Exception.Message; if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $m = $_.ErrorDetails.Message }
    "FAIL [$tag] $m"
  }
}

$base = @{ model = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'; messages = @(@{ role = 'user'; content = '用一句话解释什么是梯度下降。' }); max_tokens = 96; temperature = 0; stream = $false }
Write-Output '=== 无 --no-thinking 基线 ==='
TryReq $base 'plain'
Write-Output '=== reasoning_effort=high ==='
$o = $base.Clone(); $o['reasoning_effort'] = 'high'; TryReq $o 'effort-high'
Write-Output '=== enable_thinking=false ==='
$o2 = $base.Clone(); $o2['chat_template_kwargs'] = @{ enable_thinking = $false }; TryReq $o2 'think-off'

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
"stopped $($p.Id)"
