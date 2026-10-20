# CLAUDE.md · Local-AI

> 本文件是 Claude Code 等工具的入口说明。**完整操作约定见 [`AGENTS.md`](AGENTS.md)，其优先级高于本文件。**

## 这是什么

本地大模型工程：把 Qwen3.8-27B（IQ2，9.53 GiB）通过 NInfer 引擎跑在 12G 笔记本显卡上，
用自建 DSH 插件 `plugins/dsh-ninfer-local` 接进 DeepSeek Harness；同时是后训练工作区。

## 三条硬约束

```text
1) 只能写 D:\BaiduNetdiskDownload\Local-AI\ 之内
   D:\DrCE(26.2.16)\ 只读（可复制出来，禁止在里面写/改/删/跑脚本）
2) 仓库 private，禁止 push 到公开仓库
3) 改 plugins/dsh-ninfer-local/lib/index.js 前必须 cp .bak-thinkN，改后必须 node --check，
   并用 write 工具写脚本（不要用 shell + node -e 拼含引号的字符串）
```

## 常用命令

```powershell
# 引擎
cd D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx ; .\run-engine.ps1
curl http://127.0.0.1:1234/v1/models

# 适配器语法校验
node --check D:\BaiduNetdiskDownload\Local-AI\plugins\dsh-ninfer-local\lib\index.js

# 每请求统计（验证裁剪/采样/档位是否生效）
Get-Content D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\ninfer-stats.jsonl -Tail 3

# Python 必须全路径（PATH 里是 0 字节商店别名）
& 'C:\ProgramData\anaconda3\python.exe' --version
```

## 目录速查

```text
plugins/dsh-ninfer-local/   适配器（核心代码，PATCHES.md 记录全部改动）
train/                      后训练（权重与大产物已 gitignore）
_work/session-audit/        会话解帧与校验脚本
_research/                  模型调研备案
ninfer-csunx/               引擎（不入库）
ninfer-27b-*/               模型权重（22G，不入库）
```

## 交付风格

首行即交付物（`##` 或 ```）；结论优先、解释从简；收口一行 `当前:… / 结果:… / 下一步:…`。
