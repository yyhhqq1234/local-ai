@echo off
rem Build llama.cpp with CUDA (sm_120); NuGet SDK + local rc/mt (no spaces in paths)
set "MSVC=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207"
set "SDKROOT=D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\sdk"
set "SDKINC=%SDKROOT%\microsoft.windows.sdk.cpp\c\Include\10.0.26100.0"
set "SDKLIB=%SDKROOT%\microsoft.windows.sdk.cpp.x64\c"
set "SDKBIN=D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\sdkbin"
set "INCLUDE=%MSVC%\include;%SDKINC%\ucrt;%SDKINC%\um;%SDKINC%\shared;%SDKINC%\winrt;%SDKINC%\cppwinrt"
set "LIB=%MSVC%\lib\x64;%SDKLIB%\ucrt\x64;%SDKLIB%\um\x64"
set "PATH=%MSVC%\bin\Hostx64\x64;%SDKBIN%;C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.0\bin;%PATH%"

set SRC=D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\llama.cpp
set BUILD=%SRC%\build-cuda
set CMAKE=D:\BaiduNetdiskDownload\Local-AI\_tools\cmake-4.1.2-windows-x86_64\bin\cmake.exe
set NINJA=D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\ninja.exe

if not exist "%BUILD%\CMakeCache.txt" (
  "%CMAKE%" -S "%SRC%" -B "%BUILD%" -G Ninja ^
    -DCMAKE_MAKE_PROGRAM=%NINJA% ^
    -DCMAKE_BUILD_TYPE=Release ^
    -DCMAKE_RC_COMPILER=%SDKBIN%\rc.exe ^
    -DCMAKE_MT=%SDKBIN%\mt.exe ^
    -DGGML_CUDA=ON ^
    -DCMAKE_CUDA_ARCHITECTURES=120 ^
    -DGGML_NATIVE=OFF ^
    -DLLAMA_CURL=OFF ^
    -DLLAMA_BUILD_TESTS=OFF ^
    -DLLAMA_BUILD_EXAMPLES=OFF
  if errorlevel 1 ( echo CMAKE_CONFIGURE_FAILED & exit /b 1 )
)
"%NINJA%" -C "%BUILD%" -j 6 llama-server llama-cli
if errorlevel 1 ( echo NINJA_BUILD_FAILED & exit /b 1 )
echo BUILD_OK
dir "%BUILD%\bin\*.exe"
