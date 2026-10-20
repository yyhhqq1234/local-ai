# RUNBOOK · 从零到"改好的模型重新上线"

> **路径约定（操作者指令）**：后训练全部在**根目录**下展开，文件集中管理。
> 训练根 = `D:\BaiduNetdiskDownload\Local-AI\train\`（目录树与脚本已就位，见 `train\README.md`）。
> `$py` = `train\.venv\Scripts\python.exe`。每步都有"判据"，判据不过不要往下走。

---

## 阶段 0 · 前置（人工确认）

- [ ] D 盘 ≥120 GB 空闲（27B 串行峰值 108 GB：base 54 + merged 54；8B 峰值 32 GB）
- [ ] **训练期间退出/暂停百度网盘同步** —— 根目录在同步目录内，否则 54 GB 会被上传且与训练抢 IO
- [ ] 训练期间不跑 NInfer 引擎（会抢显存）
- [ ] 远程桌面会话下不做长跑（CUDA 长任务受会话策略影响）

> **已备好脚本（直接可用，无需手工拼命令）**
> ```
> train\scripts\setup_env.ps1   一键：Python3.12 → venv → torch cu130 → 训练栈 → 自检 → 写 .env.ps1
> train\scripts\fetch_base.py   拉基座（--size 8b|27b，--dry-run 先看体积）
> train\scripts\train_qlora.py  QLoRA 训练（--max-steps 100 冒烟；27B 自动降 ctx/升 ga）
> train\scripts\merge.py        合并 adapter（CPU，含磁盘预检与 --delete-base-after）
> train\data\train.example.jsonl 数据格式样例（3 条，可直接冒烟）
> ```
> 下面阶段 1–4 是手工等价步骤，用于排错或想逐步确认时；正常直接用脚本。

---

## 阶段 1 · 环境

```powershell
# 1.1 Python 3.12
winget install -e --id Python.Python.3.12 --scope user
refreshenv   # 或重开终端
python -V    # 判据: Python 3.12.x

# 1.2 建 venv 到非同步盘
New-Item -ItemType Directory -Path D:\BaiduNetdiskDownload\Local-AI\train -Force | Out-Null
python -m venv D:\BaiduNetdiskDownload\Local-AI\train\.venv
$py = "D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\python.exe"
& $py -V

# 1.3 torch（cu130，锁 2.11.0）
& $py -m pip install -U pip -i https://mirrors.aliyun.com/pypi/simple/
& $py -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu130

# 判据（必须全中）
& $py -c "import torch;print(torch.__version__);print(torch.version.cuda);print(torch.cuda.get_device_name(0));print(torch.cuda.get_device_capability(0));print(round(torch.cuda.get_device_properties(0).total_memory/2**30,1))"
# 期望: 2.11.0+cu130 / 13.0 / NVIDIA GeForce RTX 5070 Ti Laptop GPU / (12, 0) / 11.9

# 1.4 训练栈
& $py -m pip install "transformers>=5.8" peft trl accelerate datasets bitsandbytes==0.50.2 `
  "huggingface_hub[cli]" sentencepiece protobuf -i https://mirrors.aliyun.com/pypi/simple/

# 1.5 FlashAttention（可选，版本必须严格对齐 cp312/torch2.11/cu130）
#     从 https://hf-mirror.com/axiomofmind/flash-attention-windows-wheel-blackwell 下载对应 wheel 后本地装
& $py -m pip install .\flash_attn-2.8.4-cp312-cp312-win_amd64.whl
& $py -c "import flash_attn;print(flash_attn.__version__)"

# 1.6 bnb 自检（Blackwell 关键）
& $py -c "import bitsandbytes as b;print(b.__version__);import torch;t=torch.zeros(8,8,device='cuda');print('cuda ok')"
```

**判据**：`(12, 0)` + `11.9` + bnb 0.50.2 + `cuda ok`。任一不中，停。

---

## 阶段 2 · 基座

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"     # pypi/hf 直连不可用，必须走镜像
$env:HF_HOME     = "D:\BaiduNetdiskDownload\Local-AI\train\hf"

# 2.1 先只取 config 验证架构识别（几 KB，秒级）
& $py -c "from transformers import AutoConfig;c=AutoConfig.from_pretrained('Qwen/Qwen3.8-27B');print(type(c).__name__);print(getattr(c,'architectures',None));print(getattr(c,'model_type',None))"
# 判据: Qwen3_5Config（或等价） / ['Qwen3_5ForConditionalGeneration'] / qwen3_5
# 若 KeyError: Qwen3_5ForConditionalGeneration → transformers 版本过低，回阶段 1.4 升

# 2.2 拉全量（≈54 GiB，断点可续）
huggingface-cli download Qwen/Qwen3.8-27B --local-dir D:\BaiduNetdiskDownload\Local-AI\train\base\Qwen3.8-27B `
  --exclude "*.pth" "*.bin"

# 2.3 完整性
& $py -c "from transformers import AutoConfig,AutoProcessor;c=AutoConfig.from_pretrained(r'D:\BaiduNetdiskDownload\Local-AI\train\base\Qwen3.8-27B');print(c.text_config.num_hidden_layers, c.text_config.hidden_size)"
```

> 注：本机 `_tools\fastdl.py` 是现成的 hf-mirror 分片下载器（16 线程 + 断点续传 + sha256），比 `huggingface-cli` 更适合大文件；用法见脚本头部。

---

## 阶段 3 · 训练（QLoRA）

`D:\BaiduNetdiskDownload\Local-AI\train\train_qlora.py`：

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TrainingArguments
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer
from datasets import load_dataset

BASE  = r"D:\BaiduNetdiskDownload\Local-AI\train\base\Qwen3.8-27B"
OUT   = r"D:\BaiduNetdiskDownload\Local-AI\train\out"
DATA  = r"D:\BaiduNetdiskDownload\Local-AI\train\data\train.jsonl"
CTX   = 2048          # 12 GB 档；14B/27B 降到 512–1024
BIG   = False         # True=27B(offload) / False=8B 级

bnb = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
)

tok = AutoTokenizer.from_pretrained(BASE, trust_remote_code=True)
model = AutoModelForCausalLM.from_pretrained(
    BASE, quantization_config=bnb, dtype=torch.bfloat16,
    device_map="auto", trust_remote_code=True,
)
model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

# 关键：只挂 Transformer 的 Linear；SSM 参数(gdn/a_log, dt_bias, convolution)与 vision 一律不挂
model = get_peft_model(model, LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
))
model.print_trainable_parameters()

ds = load_dataset("json", data_files=DATA, split="train")

args = TrainingArguments(
    output_dir=OUT,
    num_train_epochs=3,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=16 if not BIG else 32,
    gradient_checkpointing=True,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    bf16=True,
    logging_steps=5,
    save_strategy="epoch",
    save_total_limit=2,
    optim="paged_adamw_8bit",
    max_grad_norm=0.3,
    report_to="none",
)

SFTTrainer(
    model=model, args=args, train_dataset=ds, tokenizer=tok,
    max_seq_length=CTX, dataset_text_field=None,
    # 数据格式: {"messages":[{"role":"user","content":...},{"role":"assistant","content":...}]}
).train()

model.save_pretrained(OUT + r"\adapter")
tok.save_pretrained(OUT + r"\adapter")
```

```powershell
& $py D:\BaiduNetdiskDownload\Local-AI\train\train_qlora.py
```

**判据**：前 20 step loss 单调下降；`nvidia-smi`（若可得）显存不持续爬满；无 `CUDA out of memory`。
**冒烟**：先 `num_train_epochs=0` 或把数据裁到 100 条，确认链路通再放大。

---

## 阶段 4 · 合并

```powershell
# CPU 上合并（避免显存不足）
& $py -c @"
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
base = AutoModelForCausalLM.from_pretrained(r'D:\BaiduNetdiskDownload\Local-AI\train\base\Qwen3.8-27B',
                                            dtype=torch.bfloat16, device_map='cpu', trust_remote_code=True)
m = PeftModel.from_pretrained(base, r'D:\BaiduNetdiskDownload\Local-AI\train\out\adapter')
m = m.merge_and_unload()
m.save_pretrained(r'D:\BaiduNetdiskDownload\Local-AI\train\merged', safe_serialization=True)
AutoTokenizer.from_pretrained(r'D:\BaiduNetdiskDownload\Local-AI\train\out\adapter').save_pretrained(r'D:\BaiduNetdiskDownload\Local-AI\train\merged')
print('merged ok')
"@
```

---

## 阶段 5 · 转 GGUF

```powershell
# 取 llama.cpp（gitee 镜像或 hf-mirror 上的镜像仓库；github.com 本机不可达）
#   git clone https://gitee.com/mirrors/llama.cpp   （或等效镜像）
& $py <llama.cpp>\convert_hf_to_gguf.py D:\BaiduNetdiskDownload\Local-AI\train\merged `
  --outfile D:\BaiduNetdiskDownload\Local-AI\train\gguf\merged-f16.gguf --outtype f16
```

---

## 阶段 6 · 转 .ninfer（回炉）

```powershell
# converter 本机已丢失，须从上游取：https://github.com/1314521gjy/ninfer-fusion-kvmem （tools/）
# github 不可达 → 走镜像 / 让上游给包
# 方向：GGUF → .ninfer（单向；无 ninfer → GGUF 的反解工具）
```

**判据**：产出的 `.ninfer` 能被 `engines\sm120a\infer-serve.exe` 加载。

---

## 阶段 7 · 上线验证

```powershell
# 备份旧模型后覆盖
Move-Item "D:\BaiduNetdiskDownload\Local-AI\ninfer-27b-kv-stream-3arch-20261019\model\<旧>.ninfer" `
          "D:\BaiduNetdiskDownload\Local-AI\ninfer-27b-kv-stream-3arch-20261019\model\<旧>.ninfer.bak"
Copy-Item "D:\BaiduNetdiskDownload\Local-AI\train\ninfer\new.ninfer" "...\model\"

# 起引擎（用原启动器，不手拼参数）
& "...\启动器.bat"
# 判据链
#   1) GET http://127.0.0.1:8080/v1/models → 200
#   2) 日志无 FATAL/ERROR/not found
#   3) 实际请求 finish_reason=stop
#   4) UI 里 mtp accepted 比例正常（投机解码未被破坏）
```

**回滚**：停引擎 → 删除新 `.ninfer` → 把 `.bak` 改回原名。

---

## 阶段 8 · 若只想验证"能力是否加上了"

最小闭环（不上线）：
1. 阶段 1–4 跑通（8B 基座即可，30 分钟内）
2. 用 adapter 直接推理对比：加 adapter 前后同一 prompt 输出差异
3. 通过后再决定是否投入 27B + 回炉成本

---

## 附：常用排错

| 症状 | 原因 | 处置 |
|---|---|---|
| `KeyError: Qwen3_5ForConditionalGeneration` | transformers < 5.8 | 升 transformers（阶段 1.4） |
| `libbitsandbytes_cuda128.dll missing` | bnb < 0.48 或 CUDA 版本错配 | 装 0.50.2 + torch cu130 |
| `no kernel image is available` | torch wheel 不含 sm_120 | 换 cu128/cu130 wheel，别用 pypi 默认 CPU 版 |
| OOM 在第一步 | ctx 过长 / batch 过大 | ctx 降到 1024、ga 提到 32、开梯度检查点 |
| loss 直接 NaN | SSM 参数被挂进 LoRA | 检查 `target_modules` 只含 7 个 Linear |
| 下载中断 | hf 直连不稳 | `HF_ENDPOINT=https://hf-mirror.com`；或用 `_tools\fastdl.py` |
| 文件"不见了" | 在百度网盘同步目录 | 训练资产移 E:/G: |
