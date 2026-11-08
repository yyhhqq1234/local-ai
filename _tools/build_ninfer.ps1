# NInfer 构建环境（工作区内，只读系统工具链）
# 用法: & _tools/build_ninfer.ps1 -Action configure|build|all

param([string]$Action = "configure")

$ErrorActionPreference = "Continue"
$VS    = "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
$CUDA  = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0"
$Root  = "D:\BaiduNetdiskDownload\Local-AI"
$CMake = Join-Path $Root "_tools\cmake-4.1.2-windows-x86_64\bin\cmake.exe"
$Ninja = Join-Path $Root "train\.venv\Scripts\ninja.exe"
$Src   = Join-Path $Root "train\lines\_shared\tools\ninfer-master"
$Build = Join-Path $Root "_tools\ninfer-build"

# NInfer 的 CMakeLists 只接受 120a（Blackwell arch-specific），120 会被拒
$Arch = "120a"

Write-Output "=== 环境自检 ==="
foreach ($p in @($CMake, $Ninja, (Join-Path $CUDA "bin\nvcc.exe"))) {
    if (Test-Path $p) { $tag = "OK" } else { $tag = "MISS" }
    Write-Output ("  {0,-5} {1}" -f $tag, $p)
}
if (-not (Test-Path $CMake)) { Write-Error "cmake 缺失"; exit 1 }
if (-not (Test-Path $Ninja)) { Write-Error "ninja 缺失"; exit 1 }

Write-Output "=== 注入 vcvars64 ==="
$vcvars = Join-Path $VS "VC\Auxiliary\Build\vcvars64.bat"
$dump = & cmd.exe /c "`"$vcvars`" >nul 2>&1 && set" 2>&1
$n = 0
foreach ($line in $dump) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        $n++
    }
}
Write-Output "  注入 $n 个环境变量"
$cl = Get-Command cl.exe -ErrorAction SilentlyContinue
if ($cl) { Write-Output ("  cl.exe: " + $cl.Source) } else { Write-Output "  cl.exe: 未找到" }

$env:PATH = "$(Split-Path $Ninja);$(Join-Path $CUDA 'bin');$env:PATH"
$env:CUDA_PATH = $CUDA

function Do-Configure {
    Write-Output "=== cmake configure (Ninja + CUDA $Arch) ==="
    $cargs = @(
        "-S", $Src,
        "-B", $Build,
        "-G", "Ninja",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_CUDA_COMPILER=$CUDA\bin\nvcc.exe",
        "-DCMAKE_CUDA_ARCHITECTURES=$Arch",
        "-DCMAKE_MAKE_PROGRAM=$Ninja"
    )
    Write-Output ("  参数: " + ($cargs -join " "))
    & $CMake @cargs 2>&1 | Select-Object -Last 30
    Write-Output "configure EXIT=$LASTEXITCODE"
    return $LASTEXITCODE
}

function Do-Build {
    Write-Output "=== cmake build ==="
    & $CMake --build $Build --parallel 8 2>&1 | Select-Object -Last 50
    Write-Output "build EXIT=$LASTEXITCODE"
}

switch ($Action) {
    "configure" { Do-Configure }
    "build"     { Do-Build }
    "all"       { $rc = Do-Configure; if ($rc -eq 0) { Do-Build } }
}


