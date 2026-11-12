param(
    [Parameter(Mandatory=$true)][string]$Ninfer,
    [string]$OutDir = ".\\ninfer-extract",
    [switch]$RawOnly
)
# ninfer-extract.ps1 —— .ninfer 容器解包：bindings 层名映射 -> 张量提取 -> 量化清单
# 用途：验证"现部署模型可否反解成可训练权重"。bf16/fp32 张量无损直出；量化块只出清单（交 ggml/gguf-py dequantize）
$ErrorActionPreference = "Stop"

$item = Get-Item -LiteralPath $Ninfer
Write-Host ("[in] " + $item.FullName + "  " + [math]::Round($item.Length/1GB,2) + " GiB")

# ---------- 1. 读头部 + JSON 索引 ----------
$fs = [System.IO.File]::OpenRead($item.FullName)
try {
    $hdr = New-Object byte[] 32
    [void]$fs.Read($hdr, 0, 32)
    $magic = [System.Text.Encoding]::ASCII.GetString($hdr, 0, 6)
    if ($magic -ne 'NINFER') { throw "magic mismatch: $magic" }
    $ver  = [BitConverter]::ToUInt16($hdr, 6)
    $jlen = [BitConverter]::ToUInt64($hdr, 8)
    Write-Host "[hdr] magic=$magic ver=$ver json_len=$jlen"
    $buf  = New-Object byte[] ($jlen + 64)
    $got = 0
    while ($got -lt $buf.Length) {
        $r = $fs.Read($buf, $got, $buf.Length - $got)
        if ($r -le 0) { break }
        $got += $r
    }
    $dataStart = 32 + $got      # 权重数据区起点（相对文件）
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
Write-Host ("[idx] objects=" + $j.objects.Count + " bindings=" + (($j.bindings.PSObject.Properties | Measure-Object).Count))

# ---------- 2. object 表（id -> 记录） ----------
$objMap = @{}
foreach ($o in $j.objects) { $objMap[$o.id] = $o }

# ---------- 3. bindings 展平：语义名 -> [{object, range|null}] ----------
$bind = @{}
foreach ($p in $j.bindings.PSObject.Properties) {
    $val = $p.Value
    if ($val.PSObject.Properties.Name -contains 'object') {
        $bind[$p.Name] = @(@{ object = $val.object; range = $null })
    } elseif ($val.PSObject.Properties.Name -contains 'parts') {
        $parts = @()
        foreach ($pt in $val.parts) { $parts += @{ object = $pt.object; range = @($pt.range[0], $pt.range[1]) } }
        $bind[$p.Name] = $parts
    }
}
Write-Host ("[bind] flattened names = " + $bind.Count)

# ---------- 4. 统计：按 dtype 分类 ----------
$quantPrefixes = @('gguf_', 'q4_', 'q5_', 'q6_', 'q8_')
$lossless = @()
$quant    = @()
foreach ($kv in $bind.GetEnumerator()) {
    foreach ($seg in $kv.Value) {
        $o = $objMap[$seg.object]
        if (-not $o) { continue }
        $fmt = [string]$o.format
        $rec = [pscustomobject]@{
            name   = $kv.Key
            object = $seg.object
            range  = if ($seg.range) { "$($seg.range[0])-$($seg.range[1])" } else { "" }
            format = $fmt
            shape  = ($o.shape -join "x")
            bytes  = [int64]$o.bytes
            offset = [int64]$o.offset
        }
        $isQuant = $false
        foreach ($qp in $quantPrefixes) { if ($fmt.StartsWith($qp)) { $isQuant = $true; break } }
        if ($isQuant) { $quant += $rec } else { $lossless += $rec }
    }
}
Write-Host ("[stats] lossless tensors = " + $lossless.Count + "  (" + [math]::Round((($lossless | Measure-Object bytes -Sum).Sum)/1GB,2) + " GiB)")
Write-Host ("[stats] quantized tensors = " + $quant.Count + "  (" + [math]::Round((($quant | Measure-Object bytes -Sum).Sum)/1GB,2) + " GiB)")

# ---------- 5. 输出 ----------
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
$meta = [pscustomobject]@{
    source     = $item.FullName
    magic      = $magic
    version    = $ver
    json_len   = $jlen
    data_start = $dataStart
    lossless   = $lossless
    quantized  = $quant
    histogram  = ($j.objects | Where-Object kind -eq 'tensor' | Group-Object format |
                  Sort-Object Count -Descending | ForEach-Object { [pscustomobject]@{ format = $_.Name; count = $_.Count } })
}
$meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutDir "manifest.json") -Encoding UTF8
$quant | Export-Csv -LiteralPath (Join-Path $OutDir "quantized.csv") -NoTypeInformation -Encoding UTF8
Write-Host ("[out] " + (Join-Path $OutDir "manifest.json"))
Write-Host ("[out] " + (Join-Path $OutDir "quantized.csv"))

if ($RawOnly) { Write-Host "[done] manifest only (-RawOnly)"; return }

# ---------- 6. 无损张量直出（raw bytes + 逐张量 .bin，供 torch 侧 frombuffer 装载） ----------
$rawDir = Join-Path $OutDir "raw"
if (-not (Test-Path $rawDir)) { New-Item -ItemType Directory -Path $rawDir -Force | Out-Null }
$fs = [System.IO.File]::OpenRead($item.FullName)
try {
    $n = 0
    foreach ($rec in $lossless) {
        $abs = $dataStart + $rec.offset
        [void]$fs.Seek($abs, [System.IO.SeekOrigin]::Begin)
        $bytes = New-Object byte[] $rec.bytes
        $read = 0
        while ($read -lt $bytes.Length) {
            $r = $fs.Read($bytes, $read, $bytes.Length - $read)
            if ($r -le 0) { break }
            $read += $r
        }
        $safe = ($rec.name -replace '[\\/:*?"<>|]', '_')
        $dst = Join-Path $rawDir ($safe + ".bin")
        [System.IO.File]::WriteAllBytes($dst, $bytes)
        if ($rec.range -ne "") { Write-Host ("  [seg] " + $rec.name + " range=" + $rec.range + " -> 需按 range 二次切分") }
        $n++
        if (($n % 100) -eq 0) { Write-Host ("  ... " + $n + " / " + $lossless.Count) }
    }
    Write-Host ("[raw] exported " + $n + " lossless tensors to " + $rawDir)
}
finally { $fs.Close() }

Write-Host "[next] 量化层补齐：用 llama.cpp/gguf-py 的 dequantize 按 quantized.csv 的 format 逐块反量化，再按 manifest 的 name 组装 safetensors"
