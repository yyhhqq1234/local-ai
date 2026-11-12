@echo off
set BASE=D:\BaiduNetdiskDownload\Local-AI\_work\infer-9b
"%BASE%\llama-bin\llama-server.exe" -m "%BASE%\gguf\kittyrev9b-Q5_K_M-im.gguf" -ngl 99 -c 8192 -b 2048 -ub 512 --host 127.0.0.1 --port 8080 --jinja --no-warmup --metrics >> "%BASE%\llama-server.log" 2>&1
