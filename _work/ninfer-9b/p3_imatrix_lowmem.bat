@echo off
rem imatrix??????+ Q5_K_M/Q4_K_M ???? imatrix?
set BIN=C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Packages\ggml.llamacpp_Microsoft.Winget.Source_8wekyb3d8bbwe
set GG=D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\gguf
set LOG=D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\imatrix2.log

echo [%TIME%] imatrix start >> %LOG%
"%BIN%\llama-imatrix.exe" -m "%GG%\kittyrev9b-f16.gguf" -f "D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\imatrix-corpus.txt" -o "%GG%\imatrix.gguf" -c 256 -b 512 -ub 512 --chunks 40 -t 8 >> %LOG% 2>&1
if errorlevel 1 ( echo [%TIME%] imatrix FAILED >> %LOG% & exit /b 1 )
echo [%TIME%] imatrix done >> %LOG%

"%BIN%\llama-quantize.exe" --imatrix "%GG%\imatrix.gguf" "%GG%\kittyrev9b-f16.gguf" "%GG%\kittyrev9b-Q5_K_M-im.gguf" Q5_K_M >> %LOG% 2>&1
echo [%TIME%] Q5_K_M-im done >> %LOG%
"%BIN%\llama-quantize.exe" --imatrix "%GG%\imatrix.gguf" "%GG%\kittyrev9b-f16.gguf" "%GG%\kittyrev9b-Q4_K_M-im.gguf" Q4_K_M >> %LOG% 2>&1
echo [%TIME%] Q4_K_M-im done >> %LOG%
echo [%TIME%] ALL DONE >> %LOG%

