$ErrorActionPreference = "Stop"
$p = "D:\BaiduNetdiskDownload\Local-AI\infer-27b-kv-stream-3arch-20261019\model\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer"

# 云盘占位导致间歇不可见：重试
$ok = $false
for ($i = 1; $i -le 5; $i++) {
    if (Test-Path -LiteralPath $p) { $ok = $true; break }
    Start-Sleep -Milliseconds 800
}
Write-Output ("file_visible=" + $ok + " attempt=" + $i)
if (-not $ok) { Write-Output "SKIP: file not visible this round"; exit 2 }

$fs = [System.IO.File]::OpenRead($p)
try {
    $hdr = New-Object byte[] 32
    [void]$fs.Read($hdr, 0, 32)
    $jlen = [BitConverter]::ToUInt64($hdr, 8)
    $buf = New-Object byte[] ($jlen + 64)
    $n = 0
    while ($n -lt $buf.Length) {
        $r = $fs.Read($buf, $n, $buf.Length - $n)
        if ($r -le 0) { break }
        $n += $r
    }
    Write-Output ("read_bytes=" + $n + " json_len=" + $jlen)
}
finally { $fs.Close() }

$txt = [System.Text.Encoding]::UTF8.GetString($buf).Trim()
$depth = 0; $end = -1; $inStr = $false; $esc = $false
for ($i = 0; $i -lt $txt.Length; $i++) {
    $c = $txt[$i]
    if ($inStr) {
        if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }
        continue
    }
    if ($c -eq '"') { $inStr = $true; continue }
    if ($c -eq '{') { $depth++ } elseif ($c -eq '}') { $depth--; if ($depth -eq 0) { $end = $i; break } }
}
$j = $txt.Substring(0, $end + 1) | ConvertFrom-Json

Write-Output "=== bindings type / count ==="
Write-Output $j.bindings.GetType().Name
if ($j.bindings -is [System.Array]) { Write-Output ("count=" + $j.bindings.Count) } else {
    Write-Output ("propcount=" + (($j.bindings.PSObject.Properties | Measure-Object).Count))
}
Write-Output "=== bindings raw head (2000 chars) ==="
$bjson = $j.bindings | ConvertTo-Json -Depth 4 -Compress
Write-Output $bjson.Substring(0, [Math]::Min(2000, $bjson.Length))

Write-Output "=== objects with non-weight/ id or name field ==="
$named = $j.objects | Where-Object { $_.PSObject.Properties.Name -contains 'name' }
Write-Output ("objects_with_name=" + ($named | Measure-Object).Count)

Write-Output "=== components.text.proposal (rows 可能含层名) ==="
$pr = $j.components.text.proposal
$pr | ConvertTo-Json -Depth 3 -Compress | ForEach-Object { $_.Substring(0, [Math]::Min(1200, $_.Length)) }

Write-Output "=== tensor 0..3 full records ==="
$j.objects | Where-Object kind -eq 'tensor' | Select-Object -First 4 | ConvertTo-Json -Depth 4 -Compress

Write-Output "=== format histogram ==="
$j.objects | Where-Object kind -eq 'tensor' | Group-Object format | Sort-Object Count -Descending |
  Select-Object Count, Name | Format-Table -AutoSize
