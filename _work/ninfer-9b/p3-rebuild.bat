@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1
"D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\ninja.exe" -C "D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build" -j 4 all
exit /b %errorlevel%
