@echo off
rem llama-server (CUDA, GPU full offload) - kittyrev9b Q5_K_M + imatrix + flash-attn
set ENG=D:\BaiduNetdiskDownload\Local-AI\engines\llama-cpp
set MODEL=D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf
set LOG=%ENG%\llama-server.log

"%ENG%\llama-bin\llama-server.exe" -m "%MODEL%" -ngl 99 -c 8192 -b 2048 -ub 1024 ^
  -fa on ^
  --host 127.0.0.1 --port 8080 ^
  --jinja --no-warmup --reasoning-format none ^
  --parallel 1 --metrics >> "%LOG%" 2>&1
