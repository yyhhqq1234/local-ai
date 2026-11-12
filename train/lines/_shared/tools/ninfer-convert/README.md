# ninfer-convert · GGUF → .ninfer 转换器（已到手并验证）

> 结论：**可运行的 GGUF 转换器已落到本目录**，入口 `python -m tools.convert`，用官方 recipe
> `qwen3_8_27b_gguf` 把混合精度 GGUF（GSQ-RCO / Q4_K / IQ3_S …）按 ggml block **逐块原样**搬进
> `.ninfer` v3 制品，不做反量化重编码。链路已用**真实 ISTA-DASLab GGUF 头部**验证到 tensor 级。
>
> 与本仓库 `train/lines/_shared/tools/ninfer-master/`（Neroued/ninfer 上游）的区别：上游那份**没有 GGUF 源**；
> 这份 fork 带 `tools/convert/gguf_blocks.py` + `sources/gguf*.py`，即 `--source gguf=…` 那条路。

---

## 1 来源与版本

| 项 | 值 |
|---|---|
| 仓库 | `iamwavecut/ninfer-all`（GitHub），分支 `master` |
| 取得方式 | `https://ghfast.top/https://github.com/iamwavecut/ninfer-all/archive/refs/heads/master.zip`（HTTP 200） |
| zip | `ninfer-all-master.zip` · 17,006,301 B · sha256 `a266836f63d219b9010d27f064d6684984c69d8d5c0b260954b647c2fcd78972` |
| 解出范围 | `tools/`、`docs/`、`AGENTS.md`、`LICENSE`、`README.md`（209 条，38 MB）；其余（`src/`、`bench/`、`tests/` 等 C++/CUDA 面）未解，转换器不需要 |
| 版本特征 | 无 `VERSION` 文件；以 zip sha256 为准。recipe 注册表含 `qwen3_8_27b_gguf` / `qwen3_8_flash_next_gguf` / `gemma4_gguf` / `bonsai2_27b_ternary` |

解压目录：`ninfer-all-master/`。**目录名保持原样**，`python -m tools.convert` 必须在它内部运行。

---

## 2 目录

```text
train/lines/_shared/tools/ninfer-convert/
├─ README.md                  ← 本文件
├─ run.cmd                    ← 一行包装：切到 ninfer-all-master 再转
├─ ninfer-all-master.zip      ← 原始 zip（可复验 sha256）
├─ ninfer-all-master/         ← 源码（转换器）
│  ├─ tools/convert/          ← 入口 __main__.py、recipe 注册、gguf_blocks.py、sources/gguf*.py
│  ├─ tools/artifact/         ← .ninfer 容器读写/布局/校验
│  ├─ tools/chat_templates/   ← qwen3_8.jinja（--resource 用）
│  └─ docs/weight-conversion.md, docs/gguf.md
└─ verify/                    ← 验证材料
   ├─ make_fake_inputs.py     ← 造最小 metadata + 假 GGUF
   ├─ inspect_header.py       ← 打印真实 GGUF 头部事实与每 tensor 的 ggml 类型
   ├─ metadata/               ← Qwen/Qwen3.8-27B 的 config / generation_config / tokenizer(.json|_config)
   ├─ fake.gguf               ← 896 B 假 GGUF（只有头，无 tensor 集）
   ├─ head-iq3s-mtp.gguf      ← 真实 GGUF 前 128 MiB（Range 取，非全量）
   └─ logs/01..04-*.txt       ← 四次实跑记录
```

---

## 3 依赖

转换器是纯 Python（CPU 即可），关键包 `gguf`（缺它会报
`reading a .gguf source requires the 'gguf' package`）。

本机已有一个满足条件的 venv（另一个工具目录里的，直接复用）：

```text
D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe
  python 3.13.9 · torch 2.14.1+cpu · gguf 0.19.0 · numpy 2.5.4
  safetensors 0.8.0 · transformers 5.20.2 · huggingface_hub 2.2.0
```

要独立环境（推荐做法，别污染）：

```bat
py -3.11 -m venv train\lines\_shared\tools\ninfer-convert\.venv-convert
train\lines\_shared\tools\ninfer-convert\.venv-convert\Scripts\python.exe -m pip install ^
  torch --index-url https://download.pytorch.org/whl/cpu
train\lines\_shared\tools\ninfer-convert\.venv-convert\Scripts\python.exe -m pip install ^
  gguf numpy safetensors transformers huggingface_hub
```

`run.cmd` 的 PATH 顺序：`%NINFER_PYTHON%` → `.venv-convert`（本目录）→ 兄弟目录
`ninfer-master\.venv-convert` → `python`。

---

## 4 一条可直接复制的转换命令

```bat
cd /d D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert
set PY=train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe
cd ninfer-all-master

%PY% -m tools.convert ^
  --model   "D:\path\to\metadata" ^
  --recipe  qwen3_8_27b_gguf ^
  --source  "gguf=D:\path\to\Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf" ^
  --components text,mtp ^
  --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja ^
  --device cpu ^
  --rows-per-chunk 512 ^
  --name "qwen3.8-27b-gsq-rco-iq3-s" ^
  --out  "D:\path\to\out\qwen3_8_27b_iq3s.ninfer"
```

要点（每条都是实测/源码确认的硬要求）：

```text
--model        只要 metadata，不需要权重：config.json / generation_config.json /
               tokenizer.json / tokenizer_config.json（Vision 还要 preprocessor_config.json
               + video_preprocessor_config.json），外加 chat_template.jinja（用 --resource 指也可）
--source gguf  必须是带 qwen35 头的 Qwen3.8-27B 混合精度 GGUF（block_count 64，带 -mtp 则 65）
--source mtp   可选。MTP 头在同一 GGUF 里时本 fork 直接从 blk.64 取（validate 会校验 has_mtp）；
               只有 MTP 单独一个 GGUF 时才需要 --source mtp=THAT.gguf。lcz.me 用的旧构建强制
               要求写两遍同一文件，本 fork 不强制（写也不会报错，会当独立源打开）
--components   缺省只有 text；需要投机解码就 text,mtp；Vision 再 +vision
--out          必须是新路径（不覆盖）
--device cpu   纯 CPU 可转（慢），有卡可 cuda
--rows-per-chunk 512 与 lcz.me 文章一致，实测配方值
```

GGUF 侧硬门槛（`tools/convert/gguf_blocks.py::validate`，逐条校验后才开始读数据）：

```text
general.architecture            = qwen35
qwen35.embedding_length         = 5120
qwen35.feed_forward_length      = 17408
qwen35.attention.head_count     = 24   / head_count_kv = 4 / key_length = value_length = 256
qwen35.ssm.conv_kernel          = 4    / state_size = 128 / group_count = 16
qwen35.ssm.time_step_rank       = 48   / inner_size = 6144
qwen35.full_attention_interval  = 4
qwen35.block_count              = 64（带 MTP 头 = 65）
tensor 集必须与 recipe 期望集完全相等（Qwen3.8-27B dense：866 个，含 MTP 头）
每个 tensor 的 ggml 类型必须在 18 种内（Q8_0 Q2_0 Q4_0 Q5_0 Q2_K…Q6_K IQ1_S IQ1_M
IQ2_XXS IQ2_XS IQ2_S IQ3_XXS IQ3_S IQ4_NL IQ4_XS），shape 必须匹配
```

---

## 5 验证证据（全部在本目录可复跑）

| # | 命令 | 结果 | 证明什么 |
|---|---|---|---|
| 1 | `python -m tools.convert --help` | exit 0，打印全部参数（`--model/--recipe/--source/--components/--resource/--proposal/--rows-per-chunk/--max-file-bytes`） | 转换器可运行，依赖齐全 |
| 2 | `--recipe no_such_recipe …` | `cannot load recipe file …\no_such_recipe` | recipe 解析路径可达（对照项） |
| 3 | `--recipe qwen3_8_27b_gguf --source gguf=fake.gguf` | `..\verify\fake.gguf: None blocks, expected 64 (+1 for MTP)` | metadata 四项 + chat_template 全过，GGUF 已打开并进入 validate |
| 4 | `--recipe qwen3_8_27b_gguf --components text,mtp --source gguf=head-iq3s-mtp.gguf` | `..\verify\head-iq3s-mtp.gguf: the data section is truncated` | **真实 ISTA-DASLab IQ3_S-mtp 头部全项通过**（架构/65 block/866 tensor 集/每 tensor 类型与 shape），只因只取了前 128 MiB 而止于数据段长度检查 |
| 5 | 同上再加 `--source mtp=head-iq3s-mtp.gguf` | `ValueError: cannot reshape array of size 123221952 into shape (248320,2880)`（栈在 `gguf/gguf_reader.py`） | `--source mtp=` 被当作独立源打开，真的走到了读 GGUF 张量数据这一步；失败同样源于文件被截断 |

第 4 条的头部事实（`python verify/inspect_header.py` 输出）：

```text
architecture  : qwen35
block_count   : 65
mtp head      : True
tensors       : 866
type census   : Q4_K 39 / F32 360 / IQ2_S 17 / IQ4_XS 96 / IQ2_XS 9 / IQ2_XXS 5 /
                BF16 96 / IQ3_XXS 78 / IQ3_S 144 / Q2_K 13 / IQ1_M 1 / Q6_K 8
mtp tensor formats: blk.64.attn_q/k/v/output/ffn_*/nextn.eh_proj → Q6_K（逐块原样导入）
expected set match: True
```

即：**除“把 10 GiB 权重读进来”这一步，转换器对真实制品的所有校验都已通过**。剩余风险只有
数据段读写与写出阶段；那需要全量 GGUF（12.1 GB 源 / 约 54 GB 中间可能量），按约束未跑。

---

## 6 复跑方法

```bat
cd /d D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-convert

:: 1) 造最小输入（假 GGUF + metadata 骨架）；metadata 真实文件可直接从 hf-mirror 拉
..\ninfer-master\.venv-convert\Scripts\python.exe verify\make_fake_inputs.py

:: 2) 头部事实
..\ninfer-master\.venv-convert\Scripts\python.exe verify\inspect_header.py

:: 3) 四次实跑（结果见 verify\logs）
cd ninfer-all-master
..\..\ninfer-master\.venv-convert\Scripts\python.exe -m tools.convert --model ..\verify\metadata ^
  --recipe qwen3_8_27b_gguf --source gguf=..\verify\fake.gguf --components text ^
  --resource chat_template.jinja=tools/chat_templates/qwen3_8.jinja --device cpu ^
  --name fake --out ..\verify\out.ninfer
```

真实 GGUF 头部（128 MiB，Range 取，不落全量）：

```bash
curl -L -r 0-134217727 \
  "https://hf-mirror.com/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF/resolve/main/Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp.gguf" \
  -o verify/head-iq3s-mtp.gguf
```

metadata（四件套，直接来自官方仓库）：

```bash
for f in config.json generation_config.json tokenizer_config.json tokenizer.json; do
  curl -L "https://hf-mirror.com/Qwen/Qwen3.8-27B/resolve/main/$f" -o verify/metadata/$f
done
```

---

## 7 已知限制 / 注意

- **未跑全量转换**：54 GB 级中间量与 12.1 GB 源 GGUF 未拉取，数据段写入路径未实测。
  要推进只需把 `--source gguf=` 指向完整文件并给 `--out` 一个约 12 GB 空位。
- 本 fork 面向 Linux/sm_86 的构建链；**转换器是纯 Python**，与 CUDA 构建无关，Windows 可跑
  （已实测）。`ninfer-serve.exe` 仍只能用 `ninfer-csunx/engine.zip` 里那份，不要用本源码重编。
- 上游文档 `docs/weight-conversion.md` 的示例路径是 POSIX 写法；Windows 用反斜杠或引号即可。
- GGUF 的 `ssm_alpha/ssm_beta` 若以 Q8_0 存（Underdog-Saluki 系），会被舍入成 BF16——这是
  recipe 唯一会改动数值的地方（源码注释明示）。
- 与 `train/lines/_shared/tools/ninfer-master/` 的关系：同一 CLI，但那棵树没有 `gguf_blocks.py`，只能吃
  safetensors 检查点。**要 GGUF 输入就走本目录。**
