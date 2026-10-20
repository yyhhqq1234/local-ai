# 后训练工作区（根目录版）

> 操作者约定：**后训练全部在根目录 `D:\BaiduNetdiskDownload\Local-AI\` 下展开，文件集中在根目录便于管理。**
> 本目录即工作区内的训练根 `train\`，所有路径不再出根目录。

---

## 1 布局（全部在根目录内）

```
D:\BaiduNetdiskDownload\Local-AI\
├── train\                    ← 训练根（本目录）
│   ├── .venv\                Python 3.12 虚拟环境（setup_env.ps1 建）
│   ├── base\                 基座权重（Qwen3.8-27B 或 8B 替代）
│   ├── data\                 训练数据（train.jsonl / eval.jsonl）
│   ├── out\                  adapter 输出（LoRA 权重，小）
│   ├── merged\               合并后全量权重（大，用完即删）
│   ├── gguf\                 HF→GGUF 中间产物（大，用完即删）
│   ├── ninfer\               ninfer-v3 converter 产出（回炉成品）
│   ├── hf\                   HF_HOME 缓存（下载分片）
│   ├── logs\                 训练日志 / timings / nvidia-smi 采样
│   ├── scripts\              setup_env.ps1 · train_qlora.py · merge.py
│   └── tmp\                  临时（下载分片、导出中间件）
├── model 包（既有）           模型包-20260930\  ninfer-27b-...\model\   ← 部署侧，不要动
├── _research\                分析备案（含本次评估包）
└── _tools\                   现成工具（fastdl.py 等）
```

---

## 2 磁盘预算（关键，D 盘只剩 175.2 GB）

| 方案 | 基座 | 合并后 | GGUF f16 | 串行峰值 | 判定 |
|---|---|---|---|---|---|
| **8B** | 16 GB | 16 GB | 16 GB | **32 GB** | ✓ 宽裕 |
| **27B** | 54 GB | 54 GB | 54 GB | **108 GB** | △ 可行，必须串行删 |

**27B 的正确串行顺序（否则爆盘）**

```powershell
# ① 下基座（54 GB）        → 占用 54
# ② QLoRA 训练（4-bit，不落大文件）→ 占用 54（out\adapter 只有几十 MB）
# ③ 合并到 merged\（+54）  → 占用 108   ← 峰值
# ④ 转 GGUF f16（+54）     → 占用 162   ← 超过则先删中间件
#    正确顺序：③ 完成后 → 转 GGUF → **确认 GGUF 可用再删 merged**
# ⑤ 转 .ninfer（约 9-15 GB）→ 删 gguf\ 与 base\（如不再训练）
```

**硬规则**：`base\` `merged\` `gguf\` 三者任一时间最多并存两个。每次进入下一阶段前先确认剩余空间：

```powershell
Get-PSDrive D | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB,1)}}
```

---

## 3 云盘同步风险与规避（根目录方案的唯一代价）

根目录在 **百度网盘同步目录**内，实测过同一路径「`Test-Path` False → `listdir` 空 → `-Recurse` 又能列出」的间歇不可见（`.ninfer`、`python.exe` 都复现过）。

规避措施（按优先级）：

1. **训练期间退出百度网盘 / 暂停该目录同步** —— 最有效；否则 54 GB 权重会被上传，且同步进程与训练抢 IO。
2. `train\tmp`、`train\hf`、`train\base`、`train\merged`、`train\gguf` 若支持同步排除，全部加排除。
3. 大文件操作（复制/合并/转换）前后各查一次 `Test-Path`；脚本内已内置重试。
4. 训练产物（adapter 几十 MB）建议立即复制一份到 `_research\` 或另行备份，避免被同步中断损坏。

> 若后续仍要换盘：只改 `$TrainRoot` 一个变量（脚本内已参数化），目录结构不变。

---

## 4 开跑顺序

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train

# ① 建环境（需联网，winget 装 Python 3.12 → venv → torch cu130 → 训练栈 → 自检）
powershell -ExecutionPolicy Bypass -File .\scripts\setup_env.ps1

# ② 取基座（默认 8B，快速验证链路；--size 27b 走大模型）
& .\.venv\Scripts\python.exe .\scripts\fetch_base.py --size 8b

# ③ 训练（先 100 步冒烟）
& .\.venv\Scripts\python.exe .\scripts\train_qlora.py --size 8b --max-steps 100

# ④ 正式训练
& .\.venv\Scripts\python.exe .\scripts\train_qlora.py --size 8b --epochs 3

# ⑤ 合并 → ⑥ 转 GGUF → ⑦ 转 .ninfer → ⑧ 部署验证
#    详见 ..\_research\微调能力-备案-20261020\04-RUNBOOK.md
```

---

## 5 与备案包的关系

- 判定依据 / 证据 / 路径记录：`..\_research\微调能力-备案-20261020\`（`03-FINDINGS.md` 有全部"能做/不能做"）
- 命令细节 / 排错表：同包 `04-RUNBOOK.md`
- 模型身份（Qwen3.8 vs `Qwen3_5*` 类名）：同包 `05-MODEL-ID.md`

**本目录只放运行时资产与脚本，不放分析文档。**
