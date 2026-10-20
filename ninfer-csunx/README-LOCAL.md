# 本地调优落地记录 — CSUNX233 配方 × Qwen3.8-27B-IQ2_S-mtp

> 依据：https://github.com/CSUNX233/qwen3.8-27b-ninfer-5070tilaptop-kvmem-local-agent v0.1.3
> 本机：RTX 5070 Ti Laptop 12GB / i7-14650HX / 32GB RAM / Windows / 驱动 617.42

## 1. 补齐了什么（原包 → 现在）

| 项 | 原包 `ninfer-27b-kv-stream-3arch-20261019` | 现在 | 状态 |
|---|---|---|---|
| 引擎 | fusion-arch-20261019（sm120a，710 MB） | **CSUNX v0.1.3**（1.35 GB，build `v0.6.0-rtx3090-1215-gad64e4e1-dirty`） | ✅ 已换 |
| `NINFER_KVMEM_INDEX_HOST` | ❌ 不支持 | ✅ | RAM 检索索引，省 ~224 MiB 显存 |
| `NINFER_KV_RING` | ❌ | ✅ | ring 长历史总开关 |
| `NINFER_KV_SINK` | ✅（4 处） | ✅ | 首部 sink 页 |
| `NINFER_HOST_PAGEABLE` | ✅ | ✅ | host 可分页 KV |
| `NINFER_KV_LEASE_RING` | ❌ | ✅ | |
| `NINFER_KVMEM_HARVEST_TEXT` | ❌ | ✅ | 文本 harvest |
| `NINFER_KVMEM_INDEX_DECODE` | ❌ | ✅ | decode 期建索引 |
| `NINFER_KVMEM_CACHE_QUERY` | ❌ | ✅ | 查询缓存 |
| `chat_template_qwen3.8-enhanced.jinja` | ❌ 无 | ✅ 已放入根目录 | 修 Qwen3.8 模板问题 |
| 页池 | 98,304 tok 全塞 GPU | **36,864 tok + 7 GiB Host KV 分层** | ✅ |
| KV 编码 | rk2v4-e8 | **nvfp4** | ✅ |
| prefill chunk | 4096 | **128** | ✅ |
| MTP | draft 1 / window 8 | **draft 3** | ✅ |
| GDN 状态 | 未开 | **`--gdn-state-fp16`** | ✅ |
| CUDA Graph 预留 | 未设 | **64 MiB** | ✅ |
| 视觉 | 无（旧模型无 vision 组件） | **`--vision-cpu`，视觉塔不驻显存** | ✅ |

引擎 exe sha256 `444b88219b5d9c8b1052c2ff37bc48320ed87bbd082b1dbca50e8cf91aaccb8d`，
归档 sha256 `e2a306a0fdfa489e3657c329c0287b3f4e45638de68bc520b897396ac998c2be`（已校验 MATCH）。

## 2. 启动

```powershell
# 纯文本（最大上下文/最省显存）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\run-engine.ps1 -NoVision

# 视觉走 CPU（不占显存，单图 256 cap；推荐）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\run-engine.ps1 -VisionCpu

# 视觉 overlay（用时上卡，512 cap；显存紧张时慎用）
pwsh -NoProfile -ExecutionPolicy Bypass -File .\run-engine.ps1
```

API：`http://127.0.0.1:1234/v1`，模型 id `qwen3.8-27b-ablit-swift15-iq2s`

阶梯加压：`-DeviceKV 36864`（起步）→ `40960` → `45056`，每次只加一档并记录 `free` 余量。

## 3. 本机实测（2026-10-20）

| 项 | 读数 |
|---|---|
| 引擎启动总耗时 | 8.1 s（首次含 CUDA Graph 14.9 s） |
| 权重加载 | 8.93 GiB / 3.1 s / 2.85 GiB/s |
| KV 容量 | 36,864 tok，nvfp4，pages 576/4096 |
| runtime | 993.2 MiB，**free 822.6 MiB** |
| Host KV | 7.00 GiB pinned |
| 检索索引 | 256.2 MiB，host-mapped-staged，score_scratch 32 MiB |
| GPU 占用 | 11,174 / 12,227 MiB |
| 短请求 decode | **68.0 tok/s**（4.41 s / 300 tok，含 227 思考） |
| 8.1K 冷 prefill | **707 tok/s**（11.46 s） |
| 8.1K 缓存重复 prefill | **8,544 tok/s**（0.95 s，cached 8,100） |
| 8.1K needle | 817 tok/s |
| 视觉（CPU 路径，96×96 PNG） | 7.20 s，正确识别红/蓝/白与白块居中，`modalities.vision=true` |

对比原包：prefill 1.18–1.77k、decode 38–61（短输入口径）；本次 8K 输入 cold 707 / cached 8,544，decode 68。

## 4. 注意事项

1. **媒体缓存默认 1 GiB + live 2 GiB**（日志 `media | 16 preprocess workers | cache 1.00 GiB | live 2.00 GiB`）——实测占 host RAM，不占 GPU（free 仍 822.6 MiB）；显存真紧张时可用 `--media-cache-mib 256 --media-live-mib 512` 压。
2. **必须为 `ninfer-serve.exe` 单独禁用 CUDA Sysmem Fallback**（NVIDIA 控制面板 → 管理 3D 设置 → 程序设置 → 添加该 exe → `CUDA - Sysmem Fallback Policy` = Prefer No Sysmem Fallback）。否则显存差 4 MB 时驱动静默回落 RAM，prefill 会从 1500 掉到 50 tok/s。
3. **7 GiB Host KV 必须保留**，它是 KVMem 主动管理的 RAM 历史缓存，和驱动回退是两件事。
4. 换档时只加 `-DeviceKV`，不要同时缩小 sink/recent/retrieve。
5. 视觉 CPU 模式：单图 256 cap 约 9.6 s（CSUNX 实测），512 cap 约 32 s，1024 cap 约 93 s。要识别小字必须提 cap，但延迟随之上升。

## 5. 文件

```
ninfer-csunx/
├─ run-engine.ps1                                 启动器（参数/环境变量全量固化）
├─ chat_template_qwen3.8-enhanced.jinja           Qwen3.8 修版模板
├─ runtime/engine/ninfer-serve.exe                CSUNX v0.1.3 引擎
├─ runtime/engine/*.dll                           13 个运行时 DLL（沿用原包）
├─ logs/                                          每次启动一个日志
└─ engine.zip                                     原始归档（可删）
```
