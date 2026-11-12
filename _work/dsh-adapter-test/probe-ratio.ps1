$exe = 'D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build\apps\ninfer-serve.exe'
$model = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$port = 1664
$log = 'D:\BaiduNetdiskDownload\Local-AI\_tools\ctx-ratio.log'
Get-Process ninfer-serve -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
$argv = @($model,'--max-context','16384','--port',"$port",'--greedy','--host-context-mib','2048','--prefill-chunk','128','--no-thinking')
$p = Start-Process -FilePath $exe -ArgumentList $argv -PassThru -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
$sw=[Diagnostics.Stopwatch]::StartNew(); $ok=$false
while($sw.Elapsed.TotalSeconds -lt 120){ Start-Sleep -Milliseconds 400; if($p.HasExited){break}; try{$null=Invoke-RestMethod "http://127.0.0.1:$port/v1/models" -TimeoutSec 2;$ok=$true;break}catch{} }
"ready=$ok"

function Ratio($text, $tag) {
  $body = @{ model='kittyrev-oxcoder9b-nsfw-gate-full-GSQ'; messages=@(@{role='user';content=$text}); max_tokens=8; temperature=0; stream=$false } | ConvertTo-Json -Depth 6 -Compress
  try {
    $null = Invoke-RestMethod "http://127.0.0.1:$port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 120
  } catch { "FAIL $tag " + $_.Exception.Message; return }
  Start-Sleep -Milliseconds 300
  $line = (Select-String -Path ($log + '.err') -Pattern 'req#\d+ done' | Select-Object -Last 1).Line
  $m = [regex]::Match($line, 'prompt ([\d,]+)')
  $tok = if ($m.Success) { [int]($m.Groups[1].Value -replace ',','') } else { -1 }
  "chars=$($text.Length) prompt_tokens=$tok ratio_chars_per_token=$([math]::Round($text.Length / [math]::Max(1,$tok),2)) [$tag]"
}

Write-Output '=== 中文纯文本 ==='
Ratio ('本地推理引擎需要在有限显存下运行，' * 100) 'zh'
Write-Output '=== 英文纯文本 ==='
Ratio ('The local inference engine must run under limited VRAM and ' * 60) 'en'
Write-Output '=== 混合（中文+标点+英文术语）==='
Ratio ('本地引擎 ninfer-serve.exe 使用 --prefill-chunk 128 与 --no-thinking 参数启动。' * 60) 'mix'

Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
"stopped"
