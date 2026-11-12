# @dsh-external/dsh-local-ai

NInfer 本地模型后端 + 引擎运维插件。

## 它做什么

1. **模型后端**：把本地 NInfer 引擎（OpenAI 兼容 `http://127.0.0.1:1234/v1`）接进 DSH，
   作为独立 provider 出现在模型选择器里。路由名 `ninfer`，模型
   `qwen3.8-27b-ablit-swift15-iq2s`。
2. **运维工具**（4 个）：
   - `ninfer_status` — 运行状态、当前模型、上下文、全部参数、日志尾
   - `ninfer_engine` — `start | stop | restart`，可同时改参数
   - `ninfer_model` — `list | switch | active`，切换 `.ninfer` 文件
   - `ninfer_params` — `get | set | defaults`，改页池/HostKV/KV编码/chunk/MTP/思考强度/上下文/视觉/端口

## 安装状态

| 组件 | 位置 |
|---|---|
| provider 配置 | `~/.dsh/profiles/desktop/cordis.patch.yml` → `- id: llm-pi-ai` → `providers.ninfer` |
| 插件装配 | `profiles/desktop/package.json` 的 `dependencies` + `bundles` |
| junction | `profiles/desktop/node_modules/@dsh-external/dsh-local-ai` |
| 凭据 | 用户环境变量 `NINFER_API_KEY`（引擎无鉴权，值任意，仅满足 credential-ref 校验） |
| 引擎目录 | `D:/BaiduNetdiskDownload/Local-AI/ninfer-csunx`（`run-engine.ps1` 是唯一启动入口） |

**改完需要重启 DSH**（`cordis.yml` 是 patch 层渲染产物，直接改会被覆盖）。

## 为什么 lib/index.js 是手写运行时

本机没有 dsh 源码 checkout（`DSH_CHECKOUT` 缺失），`scripts/build.sh` 找不到 tsc。
`lib/index.js` 因此是可直接加载的运行时 ESM（无外部依赖，只用 node 内置模块）。
`src/*.ts` 保留为类型化源码，将来有 checkout 时可正常 `npm run build` 覆盖。

## 工具用法示例

```text
ninfer_status
ninfer_engine action=restart deviceKV=40960
ninfer_model action=list
ninfer_model action=switch file=Huihui-...IQ3_XXS-mtp.ninfer restartNow=true
ninfer_params action=set reasoningEffort=low restartNow=true
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `deviceKV` | 36864 | GPU 页池 token 数（576 页）。12G 卡上限约 40960，留 ≥300 MiB 余量 |
| `hostKVMiB` | 7168 | Host KV 池（RAM），KVMem 分层第二级 |
| `kvDtype` | nvfp4 | `nvfp4` 省显存 / `rk4v4` 更稳 |
| `prefillChunk` | 128 | 长上下文 KVMem 配套；纯短文本可调大 |
| `draftTokens` | 3 | MTP 投机草稿数 |
| `reasoningEffort` | high | `off/low/medium/high/xhigh/max`；**创意与精确字数任务用 `off`** |
| `maxContext` | 262144 | 逻辑上下文上限 |
| `vision` | cpu | `off` / `cpu`（不占显存，单图约 9.6s）/ `overlay`（用时才上卡） |
| `port` | 1234 | 引擎端口 |

## 已知约束

- **同一时间只能有一个 `ninfer-serve.exe`**：两个实例抢显存会触发 WDDM 驱逐（权重被踢到共享内存，服务还在但速度崩）。切换前先 `ninfer_engine action=stop`，确认 `nvidia-smi` 回落到 ~800 MiB。
- **禁用驱动的 CUDA Sysmem Fallback**（NVIDIA 控制面板 → 程序设置 → `infer-serve.exe` → 优先不回退），否则显存差 4 MB 时会静默回退，prefill 掉一个数量级。
- 图片历史不回灌：adapter 把历史 image 块转成占位文本，避免视觉 token 挤占 12G 卡的上下文。
- `ninfer_engine` 启动等待上限 150 秒；首次加载含 CUDA Graph 约 8–19 秒。
