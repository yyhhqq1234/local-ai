@echo off
chcp 65001 >nul
rem 9B 一键启动（双击即可）：默认 32K 均衡档；参数可传 fast / 32k / 128k / 256k / stop / status
cd /d "%~dp0"
"C:\ProgramData\anaconda3\python.exe" start-9b.py %*
if /i "%~1"=="stop" goto :done
if /i "%~1"=="status" goto :done
echo.
echo 引擎已在后台运行。窗口可直接关闭。
pause
:done
