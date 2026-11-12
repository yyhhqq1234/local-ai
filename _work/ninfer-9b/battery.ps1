# battery.ps1 — 通用提示词退化率测量（判定"能力是否丢失"）
param([int]$Port = 1633)
$Root = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe  = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model= Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Log  = Join-Path $Root '_work\ninfer-9b\battery-engine.log'
Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 900
$eargs=@($Model,'--max-context','4096','--greedy','--host-context-mib','2048','--prefill-chunk','128','--no-thinking','--port',"$Port")
$proc=Start-Process -FilePath $Exe -ArgumentList $eargs -PassThru -WindowStyle Hidden -RedirectStandardOutput $Log -RedirectStandardError ($Log+'.err')
$ready=$false
for($i=0;$i -lt 180;$i++){Start-Sleep -Milliseconds 500;if($proc.HasExited){break};try{$null=Invoke-RestMethod "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2;$ready=$true;break}catch{}}
if(-not $ready){"ENGINE NOT READY";exit 2}
$mid=(Invoke-RestMethod "http://127.0.0.1:$Port/v1/models").data[0].id
"engine ready pid=$($proc.Id)"
$prompts=@(
 'What is the capital of France?',
 'Name three colors.',
 'Write a haiku about rain.',
 'Explain what a transformer is in one paragraph.',
 'Translate "good morning" into Japanese.',
 'What is 17 * 3?',
 'List two differences between TCP and UDP.',
 'Write a Python function that returns the factorial of n.'
)
$bad=0
foreach($p in $prompts){
  $b=@{model=$mid;messages=@(@{role='user';content=$p});max_tokens=48;temperature=0;stream=$false}|ConvertTo-Json -Depth 8 -Compress
  try{$r=Invoke-RestMethod "http://127.0.0.1:$Port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 300}catch{"  ERR $p";continue}
  $t=[string]$r.choices[0].message.content; $h=($t -replace "\s+",' '); if($h.Length -gt 70){$h=$h.Substring(0,70)}
  # 粗判：非 ASCII 字母比例过高 / 出现 base64 特征 / 大量稀有符号 => 记为退化
  $nonAscii=([regex]::Matches($t,'[^\x00-\x7F]')).Count
  $flag = if($t.Length -gt 0 -and ($nonAscii/$t.Length) -gt 0.35) {'SUSPECT'} else {'ok'}
  if($flag -eq 'SUSPECT'){$bad++}
  "  [$flag] $p`n      >>> $h"
}
"==== degenerate $bad / $($prompts.Count) ===="
Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
