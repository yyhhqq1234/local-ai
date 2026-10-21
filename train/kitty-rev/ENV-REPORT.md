# ENV-REPORT · 训练环境与基座实测（2026-10-21 00:50）

> 结论先说：**训练栈可装（Python 3.13 + torch cu130 有 cp313 wheel），基座缺失，converter 缺失。**
> 显存是当前最大现实约束：12 GB 卡已被桌面占用 6.4 GB，训练前必须清场。

---

## 1 实测事实（命令 + 原始结果）

| 项 | 命令 | 结果 |
|---|---|---|
| 系统 Python | `python -V`（PATH 首位） | WindowsApps 0 字节别名（不可用） |
| 真解释器 | `C:\ProgramData\anaconda3\python.exe -V` | **3.13.9** |
| Python 3.12 | `py -3.12 -V` | **不存在**（py 启动器也没有） |
| pip | `python -m pip -V` | pip 25.3（可用） |
| 训练 venv | `ls train/.venv` | **不存在** |
| 训练栈 | import torch/transformers/peft/trl/bnb/datasets/accelerate | **全部 MISSING** |
| 基座权重 | `ls train/base/` | **空目录** |
| converter | `ninfer-csunx/engine.zip` 条目清单 | 只有 `ninfer-serve.exe` + 许可证，**无转换工具** |
| 磁盘 | `df -h /d` | 631G 总 / **291G 可用** |
| GPU | `nvidia-smi` | RTX 5070 Ti Laptop **12227 MiB**，**已用 6404 MiB** |
| GPU 占用者 | `nvidia-smi --query-compute-apps` | dwm / SearchHost / explorer / Steam++（桌面合成器，非训练） |
| 引擎进程 | `tasklist \| grep infer` | **无**（确认已停） |
| hf-mirror | `curl hf-mirror.com/api/models` | **200** |
| 阿里云 pypi | `curl mirrors.aliyun.com/pypi/simple` | **200** |

---

## 2 关键修正：3.12 不是硬约束

`docs/06` 里写的「Python 3.12」是当时的保守值。实测两条 wheel 线都支持 **cp313 / py3-none-win**：

```text
torch cu130  index  : torch-2.9.0 / 2.9.1 / 2.13.0 / 2.14.0 / 2.14.1 +cu130-cp313-cp313-win_amd64.whl
bitsandbytes 0.50.2 : bitsandbytes-0.50.2-py3-none-win_amd64.whl（纯 wheel，含 DLL，无本地编译）
```

→ **直接用 anaconda 3.13 建 venv，不必先装 3.12**。torch 版本建议锁 `2.9.1+cu130`（与 bnb 0.50.2 组合在 docs/06 §5 的退路一致），或试 `2.14.1+cu130`（更新，风险未验）。

---

## 3 装环境（一次性，全部在工作区内）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train

# 3.1 用 anaconda 3.13 建 venv（不污染 base）
& "C:\ProgramData\anaconda3\python.exe" -m venv .venv
$py = "D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\python.exe"

# 3.2 基础工具 + torch cu130（cp313）
& $py -m pip install -U pip setuptools wheel -i https://mirrors.aliyun.com/pypi/simple/
& $py -m pip install "torch==2.9.1+cu130" --index-url https://download.pytorch.org/whl/cu130

# 3.3 训练栈（transformers 必须 ≥5.8，能识别 Qwen3_5ForConditionalGeneration）
& $py -m pip install -U "transformers>=5.8" peft trl accelerate datasets bitsandbytes==0.50.2 `
    -i https://mirrors.aliyun.com/pypi/simple/

# 3.4 验真（三条都要过）
& $py -c "import torch;print(torch.__version__, torch.cuda.get_device_capability(0), torch.cuda.get_device_properties(0).total_memory/2**30)"
& $py -c "import transformers;print(transformers.__version__)"
& $py -c "import bitsandbytes as b;print(b.__version__)"
```

判据：
```text
torch 2.9.1+cu130 / capability (12, 0) / total_memory ≈ 11.9 GiB
transformers ≥ 5.8
bitsandbytes 0.50.2
```

**不可用路径记录**：
- `pip install bitsandbytes`（默认源）→ 装到 CPU 版或版本不符，运行时报 `no kernel image is available`
- 自编 flash-attn / deepspeed / bitsandbytes → 本机无 MSVC，必失败
- WSL/Linux 栈 → 未启用，不绕

---

## 4 基座（54 GiB，先确认磁盘与带宽）

```powershell
$py = "D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\python.exe"
$env:HF_ENDPOINT = "https://hf-mirror.com"
& $py ..\scripts\fetch_base.py --size 8b     # 先用 8B 验链路（16 GiB）
& $py ..\scripts\fetch_base.py --size 27b    # 27B 主链（54 GiB，291G 可用，够）
```

判据：`AutoConfig.from_pretrained(base).architectures == ['Qwen3_5ForConditionalGeneration']`。

**风险**：D 盘在百度网盘同步目录内。54 GiB 会被上传并与训练抢 IO → 训练期必须暂停同步或把 `train\base|merged|gguf|hf|tmp` 加排除。

---

## 5 显存现实（这是本机最硬的一条）

```text
总 12227 MiB
桌面已占 6404 MiB（dwm / SearchHost / explorer / Steam++ 等合成器进程）
可用 ≈ 5800 MiB
```

| 方案 | 权重常驻 | 峰值估算 | 在 5.8 GB 下 |
|---|---|---|---|
| 8B QLoRA 4bit (NF4) | ≈4.0 GB | 6–9 GB | ✗ 需关桌面程序，或 ctx 512 + ga 32 |
| 14B QLoRA 4bit | ≈7 GB | 11–12 GB | ✗ |
| 27B QLoRA 4bit | ≈13.5 GB | — | 必 offload 到 CPU（慢，但 RAM 31.5 GB 够） |

**训练前清场**（不改系统设置，只关占用）：
```powershell
# 看谁在占显存
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv
# 训练时建议：关浏览器硬件加速、关 Steam++/壁纸类、关闭引擎
```
27B 走 offload 时判据：`device_map=auto` 下**前 20 step 不 OOM 且 loss 下降**，速度慢属正常。

---

## 6 converter（唯一硬断点，仍未解决）

`ninfer-csunx/engine.zip` 只有推理二进制 + 许可证，**没有任何 GGUF→.ninfer 转换工具**。也就是说：

```text
训练能做完 → adapter 能合并 → GGUF 能导出 → 但回不到 .ninfer → 部署链断
```

三条候选（按成本排序）：
1. 找旧工作区备份：`D:\Ab1-Swift\engine\tools`（文档说已删，先 `dir /s` 确认回收站/备份盘）
2. 上游 release / 引擎仓库里的 `ninfer-convert` 或 `gguf2ninfer`
3. 自己写：读 `.ninfer` 容器格式（已有 1422 bindings / 689 量化张量的 manifest 在 `_research/微调能力-备案-20261020/data/`），按格式回打包

**在 converter 确认之前，不要下 27B 基座（54 GiB）**——先跑 8B 验证数据与链路。

---

## 7 门槛判定（对照 docs/06 §8）

| # | 前置 | 判定 | 说明 |
|---|---|---|---|
| 1 | Python 训练栈 | **可装** | 3.13 + cu130 cp313 + bnb win wheel 已确认存在 |
| 2 | torch cu130 / sm120 | **可装** | 需实测 capability (12,0) |
| 3 | transformers ≥5.8 | **可装** | 需实测能识别 Qwen3_5* |
| 4 | 全精度基座 | **缺** | 8B 16 GiB / 27B 54 GiB，hf-mirror 可达 |
| 5 | ninfer converter | **缺（硬断点）** | engine.zip 无转换工具 |
| 6 | 磁盘 | **过** | 291 GiB 可用，27B 串行峰值 108 GiB |
| 7 | 显存 | **紧张** | 桌面占 6.4 GB，需清场；27B 必 offload |
| 8 | 训练期停同步/停引擎 | **待执行** | 引擎已停；同步需手动 |

---

## 8 建议执行顺序

```text
① 装 venv + torch + 训练栈，三条验真命令全过          （今天可做，无需下载大文件）
② 拉 8B 基座（16 GiB），跑 kitty-rev 数据 100 步冒烟    （验证数据格式 + LoRA 红线 + 显存）
③ 冒烟通过 → 并行确认 converter 来源
④ converter 到手 → 拉 27B（54 GiB）→ 正式 SFT/DPO
⑤ 部署前：旧 .ninfer 改名 .bak，新文件起引擎验 /v1/models + 真实推理
```
