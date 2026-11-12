@echo off
rem 用 NuGet 版 Windows SDK（10.0.26100.7705）替代缺失的 Windows Kits 安装
set "MSVC=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC\14.44.35207"
set "SDKROOT=D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\sdk"
set "SDKINC=%SDKROOT%\microsoft.windows.sdk.cpp\c\Include\10.0.26100.0"
set "SDKLIB=%SDKROOT%\microsoft.windows.sdk.cpp.x64\c"
set "INCLUDE=%MSVC%\include;%SDKINC%\ucrt;%SDKINC%\um;%SDKINC%\shared;%SDKINC%\winrt;%SDKINC%\cppwinrt"
set "LIB=%MSVC%\lib\x64;%SDKLIB%\ucrt\x64;%SDKLIB%\um\x64"
set "PATH=%MSVC%\bin\Hostx64\x64;%PATH%"
if "%~1"=="" goto full
"D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\ninja.exe" -C "D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build" -j 4 %*
exit /b %errorlevel%
:full
"D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\ninja.exe" -C "D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build" -j 4 apps/ninfer-serve.exe apps/ninfer.exe apps/ninfer-perplexity.exe
exit /b %errorlevel%
