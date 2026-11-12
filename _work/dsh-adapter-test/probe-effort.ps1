$addr = 'http://127.0.0.1:1234/v1/chat/completions'
function TryReq($obj, $tag) {
  $b = $obj | ConvertTo-Json -Depth 8 -Compress
  try {
    $r = Invoke-RestMethod -Uri $addr -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 120
    $c = [string]$r.choices[0].message.content
    $rc = [string]$r.choices[0].message.reasoning_content
    "OK   [$tag] content=$($c.Length) reasoning=$($rc.Length) tok=$($r.usage.completion_tokens) finish=$($r.choices[0].finish_reason)"
  } catch {
    $m = $_.Exception.Message
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $m = $_.ErrorDetails.Message }
    "FAIL [$tag] $m"
  }
}

$base = @{
  model = 'kittyrev-oxcoder9b-nsfw-gate-full-GSQ'
  messages = @(@{ role = 'user'; content = '用一句话解释什么是梯度下降。' })
  max_tokens = 48
  temperature = 0
  stream = $false
}

Write-Output '=== 基线 ==='
TryReq $base 'plain'

Write-Output '=== reasoning_effort=high ==='
$o = $base.Clone(); $o['reasoning_effort'] = 'high'
TryReq $o 'effort-high'

Write-Output '=== enable_thinking=true ==='
$o2 = $base.Clone(); $o2['enable_thinking'] = $true
TryReq $o2 'enable_thinking'

Write-Output '=== thinking_budget=256 ==='
$o3 = $base.Clone(); $o3['thinking_budget'] = 256
TryReq $o3 'thinking_budget'

Write-Output '=== chat_template_kwargs.enable_thinking ==='
$o4 = $base.Clone(); $o4['chat_template_kwargs'] = @{ enable_thinking = $true }
TryReq $o4 'template_kwargs'
