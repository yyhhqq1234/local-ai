$ErrorActionPreference = "Stop"
$p = "D:\BaiduNetdiskDownload\Local-AI\ninfer-27b-kv-stream-3arch-20261019\model\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer"
$fs = [System.IO.File]::OpenRead($p)
try {
    $hdr = New-Object byte[] 32
    [void]$fs.Read($hdr, 0, 32)
    $magic = [System.Text.Encoding]::ASCII.GetString($hdr, 0, 6)
    $ver = [BitConverter]::ToUInt16($hdr, 6)
    $jlen = [BitConverter]::ToUInt64($hdr, 8)
    Write-Output "magic=$magic ver=$ver json_len=$jlen"
    $buf = New-Object byte[] ($jlen + 64)
    [void]$fs.Read($buf, 0, $buf.Length)
}
finally { $fs.Close() }

$txt = [System.Text.Encoding]::UTF8.GetString($buf).Trim()
# 找 JSON 结束位置
$depth = 0; $end = -1; $inStr = $false; $esc = $false
for ($i = 0; $i -lt $txt.Length; $i++) {
    $c = $txt[$i]
    if ($inStr) {
        if ($esc) { $esc = $false }
        elseif ($c -eq '\') { $esc = $true }
        elseif ($c -eq '"') { $inStr = $false }
        continue
    }
    if ($c -eq '"') { $inStr = $true; continue }
    if ($c -eq '{') { $depth++ }
    elseif ($c -eq '}') { $depth--; if ($depth -eq 0) { $end = $i; break } }
}
Write-Output "json end at $end"
$json = $txt.Substring(0, $end + 1)
$j = $json | ConvertFrom-Json
Write-Output ("top keys: " + ($j.PSObject.Properties.Name -join ", "))
Write-Output "objects n = $($j.objects.Count)"
$j.objects | Group-Object kind | Select-Object Count, Name | Format-Table -AutoSize
$j.objects | Group-Object encoding | Select-Object Count, Name | Format-Table -AutoSize
Write-Output "=== object key union ==="
$keys = @{}
foreach ($o in $j.objects) { foreach ($k in $o.PSObject.Properties.Name) { $keys[$k] = 1 } }
$keys.Keys -join ", "
Write-Output "=== samples by kind ==="
foreach ($k in ($j.objects | Group-Object kind | ForEach-Object Name)) {
    $ex = $j.objects | Where-Object { $_.kind -eq $k } | Select-Object -First 2
    Write-Output "--- kind=$k"
    $ex | ConvertTo-Json -Depth 4 -Compress | Write-Output
}
Write-Output "=== components ==="
$j.components.PSObject.Properties | ForEach-Object { Write-Output ("comp: " + $_.Name + " | keys: " + ($_.Value.PSObject.Properties.Name -join ",")) }
Write-Output "=== files ==="
Write-Output ("files n=" + $j.files.Count)
$j.files | Select-Object -First 3 | ConvertTo-Json -Depth 3 -Compress | Write-Output
