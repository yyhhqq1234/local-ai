# 结构化判定 · 能力矩阵 / 路径记录 / 待办

---

## 1 能力矩阵（按"想做的事"逐条判定）

| # | 想做的事 | 判定 | 缺什么 | 备注 |
|---|---|---|---|---|
| 1 | 原地微调现 `.ninfer` | **✗ 不能** | 训练面 + 全精度权重 | 引擎纯前向；容器为量化+索引 |
| 2 | 从 `.ninfer` 反解出 bf16 再训练 | **△ 能解，不划算** | ggml 反量化实现 + HF 命名词典 | 99.5% 体量为量化，全模型近似 |
| 3 | 从 HF 拉 `Qwen3.8-27B` bf16 → QLoRA | **✓ 能**（需装环境） | Python3.12 + torch2.11cu130 + bnb0.50.2 + transformers≥5.8 | 27B 4bit 权重 13.5 GB 超 12 GB → 必 offload |
| 4 | 8B 级 QLoRA（替代方案） | **✓ 舒适** | 同上，transformers 版本要求可降 | 峰值 8–10 GB |
| 5 | 14B QLoRA | **△ 贴边** | 梯度检查点 + 短序列 | 峰值 11–12 GB |
| 6 | 27B LoRA bf16 | **✗** | 54 GB 权重 | 显存/内存双超 |
| 7 | 27B 全参微调 | **✗** | 8×A100 级 | 不成立 |
| 8 | 用 heretic 做 abliteration | **△ 仅 8B** | bf16 基座 | 需 transformers 5.x + peft 0.21 + bnb 0.50 |
| 9 | adapter 回炉成 `.ninfer` | **△ 取决工具** | ninfer-v3 converter（本机丢失） | 只能 GGUF → ninfer 单向 |
| 10 | 纯 CPU 微调 | **△ 理论可** | Python + torch CPU | 27B/31.5 GB 不可行；8B 小时级/epoch |
| 11 | iGPU（Intel Arc）训练 | **✗** | IPEX-LLM 训练支持极弱 | 不作主路径 |
| 12 | 装 FlashAttention-2（sm120/Win） | **✓ 仅一种组合** | py3.12 + torch2.11 + cu130 | 无 MSVC，不能自编 |
| 13 | 本机现在立刻开跑 | **✗** | 全部训练栈 | 无 Python/pip/uv/conda/nvcc/MSVC/WSL |

---

## 2 显存数学（12 GB 卡）

| 模型 | 方案 | 权重常驻 | 峰值 | 判定 |
|---|---|---|---|---|
| 27B | QLoRA 4bit NF4 | 27e9×0.5 B ≈ **13.5 GB** | 权重已超卡 | 必 offload |
| 27B | LoRA bf16 | 27e9×2 B ≈ **54 GB** | 54 GB+ | ✗ |
| 14B | QLoRA 4bit | 14e9×0.5 B ≈ **7 GB** | 11–12 GB | △ 贴边 |
| 8B | QLoRA 4bit | 8e9×0.5 B ≈ **4 GB** | 8–10 GB | ✓ 舒适 |

判据：**12 GB 卡舒适区 8B，14B 贴边，27B 必然 offload。**

---

## 3 路径记录（不可用路径 + 等价替代）

| 路径 | 状态 | 原因 | 替代 |
|---|---|---|---|
| 直接读 `.ninfer` 反解 bf16 | 不可用 | tensor 为 GGUF 块量化 + 无 name 字段 | 从上游拉 bf16 基座 |
| `D:\Ab1-Swift` 原始转换工作区 | 不可用 | 目录已删除（base/gguf/vision/ranking 四路径全失效） | 重新下 HF/GGUF |
| ninfer-v3 converter | 不可用 | 本机丢失（原在本机 provenance 指明的 `engine\tools`） | 从上游 `ninfer-fusion-kvmem` 仓库取 tools |
| heretic 27B abliteration | 不可用（本机） | 需 bf16 + >12 GB 显存 | 降 8B；或租卡 |
| 系统 Python / pip / uv / conda | 不可用 | 未安装，仅商店别名 | 装 Python 3.12 + venv（阿里镜像） |
| CUDA Toolkit（nvcc） | 不可用 | 未安装 | 不需要：torch wheel 自带 CUDA 运行时 |
| MSVC / VS Build Tools | 不可用 | 未安装 | 只能用预编译轮子，禁自编 FA/deepspeed/bnb |
| WSL / Linux 训练栈 | 不可用 | 未启用 | Windows 原生 transformers+peft；或启用 WSL2 |
| `pypi.org` 直连 | 不可用 | 12 s 超时 | `-i https://mirrors.aliyun.com/pypi/simple/` |
| `github.com` / `raw.githubusercontent.com` | 不可用 | DNS 解析到非公网 IP | 走 `hf-mirror.com` 取 HF 镜像仓库 |
| 嵌入式 Python 作训练解释器 | 不采用 | 无 site-packages、路径间歇不可见 | 独立安装 Python 3.12 |
| 派 subagent 拉上游矩阵 | 不可用 | 该 subagent 中途失败、无回执 | 主线程自查（已完成） |

---

## 4 版本锁定（唯一可行组合）

```
Python            3.12
torch             2.11.0+cu130 (win_amd64)   --index-url https://download.pytorch.org/whl/cu130
bitsandbytes      0.50.2  (win_amd64)
flash_attn        2.8.4   (cp312 / torch2.11 / cu130 / sm120 预编译)
transformers      >=5.8   （官方 config 标 5.8.0.dev0，需识别 Qwen3_5ForConditionalGeneration）
peft / trl / accelerate / datasets  最新稳定
```

退路（不装 FA）：`torch 2.9.1+cu128` + `bnb 0.50.2`，注意力用 SDPA，功能不缺。

**禁项**：任何需要现场编译的组件（自编 flash-attn / deepspeed / 自编 bitsandbytes）—— 本机无 MSVC。

---

## 5 模型身份（易错点，已核）

| 项 | 值 | 说明 |
|---|---|---|
| 模型 | **`Qwen/Qwen3.8-27B`** | 27B，原生多模态（text + vision + MTP） |
| HF `architectures` | `Qwen3_5ForConditionalGeneration`（顶层）/ `Qwen3_5ForCausalLM`（text） | **实现类名，非版本号** |
| `model_type` | `qwen3_5` / `qwen3_5_text` | 同上 |
| 易犯错误 | 把 `qwen3_5_text` 读成"模型是 3.5" | 与 Qwen2.5 仍用 `Qwen2ForCausalLM` 同理 |
| 架构特征 | 48×linear_attention + 16×full_attention（4 层一循环）；GDN 线性注意力 + MTP 头 | 微调时 SSM 参数不可挂 LoRA |

---

## 6 LoRA 挂载注意（该架构特有）

```python
# 正确
target_modules = ["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"]
# 禁止挂载（SSM/状态空间参数，挂上会破坏数值稳定性）
#   gdn/a_log, gdn/dt_bias, gdn/convolution, gdn/a_projection, gdn/b_projection, gdn/norm
#   vision.* (冻结)
```

---

## 7 待办（按顺序，未完成）

| # | 待办 | 阻塞点 | 交付判据 |
|---|---|---|---|
| 1 | 训练根目录（**已定：`Local-AI\train\`，根目录内集中管理**） | 该目录在百度网盘同步域内，实测间歇不可读 | 训练期间暂停同步；目录可写、`Test-Path` 稳定、`train\README.md` 布局就位 |
| 2 | 装 Python 3.12 + venv | 无系统 Python | `python -V` = 3.12.8 |
| 3 | 装 torch 2.11.0+cu130 | 无训练栈 | `torch.cuda.get_device_capability(0) == (12,0)` 且 VRAM 显示 11.9 |
| 4 | 装 bnb 0.50.2 + transformers≥5.8 | — | `AutoConfig.from_pretrained(Qwen3.8-27B).architectures == ['Qwen3_5ForConditionalGeneration']` |
| 5 | 拉 `Qwen/Qwen3.8-27B` bf16（≈54 GiB） | 带宽 + 磁盘 | 文件齐全 + `safetensors` 可加载 |
| 6 | 跑 8B 或 27B-offload QLoRA 冒烟（100 step） | 显存 | loss 正常下降、无 OOM |
| 7 | 取 ninfer-v3 converter | 本机丢失 | 能从 GGUF 产出可被 `infer-serve.exe` 加载的 `.ninfer` |
| 8 | 回炉验证 | 依赖 1–7 | 新 `.ninfer` 起引擎 `/v1/models` 200 + 实际推理通过 |

---

## 8 结论口径（对外统一）

> 本机具备 **8B 级 QLoRA 后训练能力**；对现部署的 27B `.ninfer` **不具备就地微调能力**，因为该文件是推理产物（99.5% 体量为量化块），不是训练起点。要给它加/强化能力，路径是：取同架构 bf16 基座（`Qwen/Qwen3.8-27B`）训练 → 合并 → GGUF → ninfer-v3 converter → 覆盖部署。当前卡口不在算力，在**训练环境未装 + 无全精度基座 + converter 丢失**三项。
