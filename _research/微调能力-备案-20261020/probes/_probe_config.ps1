param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"
$item = Get-Item -LiteralPath $Path
$fs = [System.IO.File]::OpenRead($item.FullName)
try {
    $hdr = New-Object byte[] 32
    [void]$fs.Read($hdr, 0, 32)
    $jlen = [BitConverter]::ToUInt64($hdr, 8)
    $buf = New-Object byte[] ($jlen + 64)
    $got = 0
    while ($got -lt $buf.Length) {
        $r = $fs.Read($buf, $got, $buf.Length - $got)
        if ($r -le 0) { break }
        $got += $r
    }
}
finally { $fs.Close() }

$txt = [System.Text.Encoding]::UTF8.GetString($buf).Trim()
$depth = 0; $end = -1; $inStr = $false; $esc = $false
for ($i = 0; $i -lt $txt.Length; $i++) {
    $c = $txt[$i]
    if ($inStr) { if ($esc) { $esc = $false } elseif ($c -eq '\') { $esc = $true } elseif ($c -eq '"') { $inStr = $false }; continue }
    if ($c -eq '"') { $inStr = $true; continue }
    if ($c -eq '{') { $depth++ } elseif ($c -eq '}') { $depth--; if ($depth -eq 0) { $end = $i; break } }
}
$j = $txt.Substring(0, $end + 1) | ConvertFrom-Json

Write-Output "=========== metadata ==========="
$j.metadata | ConvertTo-Json -Depth 6
Write-Output "=========== provenance ==========="
$j.provenance | ConvertTo-Json -Depth 6
Write-Output "=========== components.text.config (FULL) ==========="
$j.components.text.config | ConvertTo-Json -Depth 8
Write-Output "=========== components.vision.config ==========="
$j.components.vision.config | ConvertTo-Json -Depth 8
Write-Output "=========== components.mtp.config ==========="
$j.components.mtp.config | ConvertTo-Json -Depth 8
Write-Output "=========== resources ==========="
$j.objects | Where-Object kind -eq 'resource' | ConvertTo-Json -Depth 4 -Compress
Write-Output "=========== generation_config / tokenizer_config 内嵌内容的键 ==========="
foreach ($kv in $j.components.text.resources.PSObject.Properties) {
    Write-Output ("resource: " + $kv.Name + "  type=" + $kv.Value.GetType().Name)
    if ($kv.Value -is [System.Management.Automation.PSCustomObject]) {
        Write-Output ($kv.Value | ConvertTo-Json -Depth 4)
    }
}
