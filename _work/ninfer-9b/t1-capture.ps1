# t1-capture.ps1 — 抓 serve 侧每次请求的真实记录（含 prompt token 序列），用于与 CLI 路径对比
param([int]$Port = 1632)

$Root  = 'D:\BaiduNetdiskDownload\Local-AI'
$Exe   = Join-Path $Root '_tools\ninfer-build\apps\ninfer-serve.exe'
$Model = Join-Path $Root 'train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer'
$Log   = Join-Path $Root '_work\ninfer-9b\t1-engine.log'
$Req   = Join-Path $Root '_work\ninfer-9b\t1-reqlog.jsonl'
if (Test-Path $Req) { Remove-Item $Req -Force }

Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
Start-Sleep -Milliseconds 900

$eargs = @($Model,'--max-context','4096','--greedy','--host-context-mib','2048','--prefill-chunk','128',
           '--no-thinking','--port',"$Port",'--request-log-jsonl',$Req,'--log-level','trace')
$proc = Start-Process -FilePath $Exe -ArgumentList $eargs -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $Log -RedirectStandardError ($Log + '.err')
$ready=$false
for ($i=0; $i -lt 180; $i++) { Start-Sleep -Milliseconds 500; if ($proc.HasExited) { break }
  try { $null=Invoke-RestMethod "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2; $ready=$true; break } catch {} }
if (-not $ready) { "ENGINE NOT READY"; Get-Content ($Log+'.err') -Tail 5; exit 2 }
$mid=(Invoke-RestMethod "http://127.0.0.1:$Port/v1/models").data[0].id
"engine ready pid=$($proc.Id) model=$mid"

function Chat([string]$label,$msgs,[int]$mt){
  $b=@{model=$mid;messages=$msgs;max_tokens=$mt;temperature=0;stream=$false}|ConvertTo-Json -Depth 8 -Compress
  try { $r=Invoke-RestMethod "http://127.0.0.1:$Port/v1/chat/completions" -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 300 }
  catch { "  [$label] ERR $($_.Exception.Message)"; return }
  $t=[string]$r.choices[0].message.content; $h=($t -replace "\s+",' '); if($h.Length -gt 80){$h=$h.Substring(0,80)}
  "  [$label] chars=$($t.Length) >>> $h"
}

"== serve: user-only =="
Chat 'user'   @(@{role='user';content='What is 2+2?'}) 16
"== serve: system+user =="
Chat 'sys'    @(@{role='system';content='You are a helpful assistant.'},@{role='user';content='What is 2+2?'}) 16
"== serve: essay =="
Chat 'essay'  @(@{role='user';content='Write a 300-word essay about why local inference matters.'}) 24

Start-Sleep -Milliseconds 1200
Get-Process ninfer-serve -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }

"== reqlog records =="
if (Test-Path $Req) {
  $lines = Get-Content $Req
  "lines=$($lines.Count)"
  foreach ($l in $lines) {
    try { $o = $l | ConvertFrom-Json } catch { continue }
    $keys = ($o.PSObject.Properties.Name) -join ','
    "---- keys: $keys"
    foreach ($k in $o.PSObject.Properties.Name) {
      $v = $o.$k
      if ($v -is [System.Array] -and $v.Count -gt 3) { "   $k = [array $($v.Count)] first: $($v[0..4] -join ' ')" }
      elseif ($v -is [string] -and $v.Length -gt 120) { "   $k = (str $($v.Length)) " + $v.Substring(0,120) }
      elseif ($v -is [psobject] -and $v.PSObject.Properties.Name.Count -gt 3) { "   $k = { " + (($v.PSObject.Properties.Name) -join ',') + " }" }
      else { "   $k = $v" }
    }
  }
} else { "NO REQLOG" }
