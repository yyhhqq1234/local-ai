@echo off
rem 9B 均衡档（默认）：32K 设备 KV（q8_0），decode 65-72 tok/s
rem 上下文 32768 = 系统提示 ~8K + 工具/用户定义 ~8K + 对话历史 ~16K，留足余量
rem 显存：6.19G 权重 + ~2.2G KV(q8_0,32k) + ~1G runtime ≈ 9.4G / 12G
set ENG=D:\BaiduNetdiskDownload\Local-AI\engines\llama-cpp
set MODEL=D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf\kittyrev9b-Q5_K_M-im.gguf
set LOG=%ENG%\llama-32k.log

"%ENG%\llama-bin\llama-server.exe" -m "%MODEL%" -ngl 99 -c 32768 ^
  --cache-type-k q8_0 --cache-type-v q8_0 ^
  -b 1024 -ub 512 -fa on ^
  --host 127.0.0.1 --port 8080 ^
  --jinja --no-warmup --reasoning-format none ^
  --parallel 1 --metrics >> "%LOG%" 2>&1
