@echo off
rem 9B 折中档：设备 KV（q8_0），上下文 131072
rem 实测（2026-11-12）：decode 44.1 tok/s · prefill 32k 2058 tok/s（TTFT 15.9 s）· 64k 1435 tok/s
rem 显存余量 1371–1883 MB · 32k 针尖测试通过（K7Q2M9 命中）
set ENG=D:\BaiduNetdiskDownload\Local-AI\engines\llama-cpp
set MODEL=D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf
set LOG=%ENG%\llama-128k.log

"%ENG%\llama-bin\llama-server.exe" -m "%MODEL%" -ngl 99 -c 131072 ^
  --cache-type-k q8_0 --cache-type-v q8_0 ^
  -b 1024 -ub 512 -fa on ^
  --host 127.0.0.1 --port 8080 ^
  --jinja --no-warmup --reasoning-format none ^
  --parallel 1 --metrics >> "%LOG%" 2>&1
