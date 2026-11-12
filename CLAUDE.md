# CLAUDE.md · Local-AI

> 本文件是 Claude Code 等工具的入口说明。**完整操作约定见 [`AGENTS.md`](AGENTS.md)，其优先级高于本文件。**

## 这是什么

本地大模型工程：把 Qwen3.8-27B（IQ2，9.53 GiB）通过 NInfer 引擎跑在 12G 笔记本显卡上，
用自建 DSH 插件 `plugins/dsh-local-ai` 接进 DeepSeek Harness；同时是后训练工作区。

## 两条训练线（先看 `docs/plans.md`）

| 训练线 | 计划文件 | 模型 | 在哪跑 |
|---|---|---|---|
| OxCoder-9B 后训练（RE 工具路由） | `docs/plans.md` | Qwen3.5-9B | 本机 12G 卡 |
| **KittyRev-27B GEN3**（NSFW 门控 + kitty 逆向 + 保留视觉） | `docs/plans.md` | Qwen3.8-27B | 云端 GPU |

## 三条硬约束

```text
1) 只能写 D:\BaiduNetdiskDownload\Local-AI\ 之内
   D:\DrCE(26.2.16)\ 只读（可复制出来，禁止在里面写/改/删/跑脚本）
2) 仓库 private，禁止 push 到公开仓库
3) 改 plugins/dsh-local-ai/lib/index.js 前必须 cp .bak-thinkN，改后必须 node --check，
   并用 write 工具写脚本（不要用 shell + node -e 拼含引号的字符串）
```

## 常用命令

```powershell
# 引擎
cd D:\BaiduNetdiskDownload\Local-AI\engines\llama-cpp ; .\serve.bat
curl http://127.0.0.1:8080/v1/models

# 适配器语法校验
node --check D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-local-ai\lib\index.js

# 每请求统计（验证裁剪/采样/档位是否生效）
Get-Content D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\ninfer-stats.jsonl -Tail 3

# Python 必须全路径（PATH 里是 0 字节商店别名）
& 'C:\ProgramData\anaconda3\python.exe' --version
```

## 结项（2026-11-12）

```text
交付：9B GGUF（models/9b/gguf，llama.cpp）+ 27B .ninfer（engines/ninfer-27b，NInfer）
切换：python engines/switch-model.py status|9b|27b
v6 权重误删，重建见 docs/v6-rebuild.md
```

## 目录速查

```text
plugins/dsh-local-ai/   适配器（核心代码，PATCHES.md 记录全部改动）
train/                      后训练（权重与大产物已 gitignore）
_work/session-audit/        会话解帧与校验脚本
_work/_research/                  模型调研备案
engines/                    推理引擎 + switch-model.py 切档脚本
models/                     已交付模型（仅 9b/gguf/kittyrev9b-Q5_K_M-im.gguf）
```

## 交付风格

首行即交付物（`##` 或 ```）；结论优先、解释从简；收口一行 `当前:… / 结果:… / 下一步:…`。

