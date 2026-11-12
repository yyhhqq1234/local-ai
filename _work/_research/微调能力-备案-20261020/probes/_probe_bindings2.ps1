param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"

$item = Get-Item -LiteralPath $Path
Write-Output ("resolved: " + $item.FullName)
Write-Output ("size: " + $item.Length + "  modified: " + $item.LastWriteTime)

$fs = [System.IO.File]::OpenRead($item.FullName)
try {
    $hdr = New-Object byte[] 32
    [void]$fs.Read($hdr, 0, 32)
    $magic = [System.Text.Encoding]::ASCII.GetString($hdr, 0, 6)
    $jlen = [BitConverter]::ToUInt64($hdr, 8)
    Write-Output ("magic=" + $magic + " json_len=" + $jlen)
    $buf = New-Object byte[] ($jlen + 64)
    $got = 0
    while ($got -lt $buf.Length) {
        $r = $fs.Read($buf, $got, $buf.Length - $got)
        if ($r -le 0) { break }
        $got += $r
    }
    Write-Output ("json_bytes_read=" + $got)
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
Write-Output ("bindings type = " + $j.bindings.GetType().Name)
$bjson = $j.bindings | ConvertTo-Json -Depth 5 -Compress
Write-Output ("bindings_json_len = " + $bjson.Length)
Write-Output "=== bindings head 2500 ==="
Write-Output $bjson.Substring(0, [Math]::Min(2500, $bjson.Length))
Write-Output "=== proposal.text ==="
$pj = $j.components.text.proposal | ConvertTo-Json -Depth 4 -Compress
Write-Output $pj.Substring(0, [Math]::Min(1500, $pj.Length))
Write-Output "=== tensor records 0..3 ==="
$j.objects | Where-Object kind -eq 'tensor' | Select-Object -First 4 | ConvertTo-Json -Depth 4 -Compress
Write-Output "=== format histogram ==="
$j.objects | Where-Object kind -eq 'tensor' | Group-Object format | Sort-Object Count -Descending | Select-Object Count, Name | Format-Table -AutoSize
Write-Output "=== 是否存在 name 字段 ==="
$withName = $j.objects | Where-Object { $_.PSObject.Properties.Name -contains 'name' }
Write-Output ("objects_with_name = " + ($withName | Measure-Object).Count)
