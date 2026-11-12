@echo off
rem 9B 长上下文档：KV 放主机内存（--no-kv-offload），上下文 262144
rem 实测（2026-11-12）：8k prompt prefill 2877 tok/s；200k prompt prefill 714 tok/s、TTFT 98 s
rem 代价：decode 35 tok/s（短上下文）/ 11.5 tok/s（32k 上下文）
set ENG=D:\BaiduNetdiskDownload\Local-AI\engines\llama-cpp
set MODEL=D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf
set LOG=%ENG%\llama-256k.log

"%ENG%\llama-bin\llama-server.exe" -m "%MODEL%" -ngl 99 -c 262144 --no-kv-offload ^
  --cache-type-k q8_0 --cache-type-v q8_0 ^
  -b 2048 -ub 1024 -fa on ^
  --host 127.0.0.1 --port 8080 ^
  --jinja --no-warmup --reasoning-format none ^
  --parallel 1 --metrics >> "%LOG%" 2>&1
