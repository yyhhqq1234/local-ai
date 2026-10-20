# 证据链 · 每条结论 ↔ 命令 ↔ 原始输出

> 规则：只记录本机实测。外部索引（wheel/仓库）标注来源 URL，不标"实测"。

---

## E-01 硬件：GPU 显存 11.9 GB（非 4 GB）

**结论**：RTX 5070 Ti Laptop GPU，VRAM 11.9 GB，驱动 32.0.16.1742。

**命令**
```powershell
Get-CimInstance Win32_VideoController | Select Name,DriverVersion,@{n='VRAM_GB';e={[math]::Round($_.AdapterRAM/1GB,1)}}
Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*" |
  Where-Object { $_.DriverDesc -match 'NVIDIA' } |
  Select DriverDesc,@{n='VRAM_GB';e={[math]::Round($_.'HardwareInformation.qwMemorySize'/1GB,1)}}
```

**原始输出**
```
Name : GameViewer Virtual Display Adapter   DriverVersion : 15.6.5.199   VRAM_GB : 0
Name : NVIDIA GeForce RTX 5070 Ti Laptop GPU DriverVersion : 32.0.16.1742 VRAM_GB : 4   ← WMI 截断，不可信
Name : Intel(R) Graphics                    DriverVersion : 32.0.101.8331 VRAM_GB : 2

DriverDesc : NVIDIA GeForce RTX 5070 Ti Laptop GPU
VRAM_GB    : 11.9        ← 注册表 qwMemorySize，采用此值
DriverVer  : 32.0.16.1742
```

**旁证**：`ninfer-27b-kv-stream-3arch-20261019\engines\` 存在 `sm120a`（Blackwell），MANIFEST 载明覆盖 RTX 50 系。

---

## E-02 硬件：CPU / RAM / OS / 磁盘

```
Intel(R) Core(TM) Ultra 7 270HX Plus   NumberOfCores 20  NumberOfLogicalProcessors 20
RAM_GB : 31.5
Microsoft Windows 11 专业版  10.0.22631
C 122.0 / D 164.5 / E 326.3 / G 149.1  (FreeGB)
```

---

## E-03 部署模型清单：4 个 .ninfer，全盘无 bf16/safetensors 大件

**命令**
```powershell
Get-ChildItem D:\,E:\ -Recurse -Depth 4 -Include *.gguf,*.safetensors,*.pth,*.pt,*.ninfer |
  Where-Object { $_.Length -gt 1GB } | Select Length,FullName
```

**原始输出**
```
7.13 GiB  ...\模型包-20260930\Ternary-Bonsai-2-27B-ninfer-v3-mtponly.ninfer
8.87 GiB  ...\模型包-20260930\Ternary-Bonsai-2-27B-ninfer-v3.ninfer
9.55 GiB  ...\ninfer-27b-...\model\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer
7.13 GiB  ...\ninfer-27b-...\model\Ternary-Bonsai-2-27B-ninfer-v3-mtponly.ninfer
```
→ **无任何 >1 GB 的 .gguf / .safetensors / .pth**，即无全精度基座。

---

## E-04 容器结构：NINFER v768，objects 1192，bindings 1422

**命令**（`probes\_probe_bindings2.ps1` / `probes\ninfer-extract.ps1 -RawOnly`）

**原始输出**
```
[in] ...Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer  9.55 GiB
[hdr] magic=NINFER ver=768 json_len=352224
[idx] objects=1192 bindings=1422
[bind] flattened names = 1422
[stats] lossless tensors = 733  (0.06 GiB)
[stats] quantized tensors = 689  (12.75 GiB)
```
补充：`json_bytes_read=352288`，`hash16=3f66a84d0c9b45af9f321b537489ea5c`（头 16..32 字节）。

---

## E-05 权重体量：99.5% 是量化块

**格式直方图（1186 tensor）**
```
582 bf16        96 fp32        2 int32
 75 gguf_iq3_xxs  63 gguf_iq3_s   58 gguf_iq2_s   56 gguf_iq2_xxs
 54 q4_g64_fp16   54 q5_g64_fp16  47 gguf_q2_k    42 gguf_iq2_xs
 17 gguf_iq1_m    16 gguf_iq4_xs    9 gguf_q4_k     7 gguf_iq1_s
  5 gguf_q6_k      2 q8_g32_fp16    1 q6_g64_fp16
```
**关键修正**：无损张量占"个数"57%，只占"体量" 0.5%（0.06 / 12.81 GiB）。embedding / attention / MLP 全为量化块。

**样例 tensor 记录**
```json
{"id":"weight/000000","shape":[16384,5120],"format":"gguf_iq3_s","layout":"gguf_blocks_v1","offset":12838144,"bytes":36044800,"kind":"tensor"}
{"id":"weight/000001","shape":[10240,5120],"format":"gguf_iq2_xxs","layout":"gguf_blocks_v1","offset":48882944,"bytes":13516800,"kind":"tensor"}
```

---

## E-06 bindings 提供完整层名映射（反解可行性的关键）

**原始输出（bindings 前段）**
```json
{"text/token_embedding":{"object":"weight/000122"},
 "text/output_head":{"object":"weight/000123"},
 "text/final_norm":{"object":"weight/000124"},
 "text/layers/0/input_norm":{"object":"weight/000125"},
 "text/layers/0/gdn/a_log":{"object":"weight/000126"},
 "text/layers/0/gdn/dt_bias":{"object":"weight/000127"},
 "text/layers/0/gdn/convolution":{"object":"weight/000128"},
 "text/layers/0/gdn/a_projection":{"object":"weight/000129"},
 "text/layers/0/gdn/b_projection":{"object":"weight/000130"},
 "text/layers/0/gdn/query":{"parts":[{"object":"weight/000000","range":[0,10485760]}]},
 "text/layers/0/gdn/key":{"parts":[{"object":"weight/000000","range":[10485760,20971520]}]},
 "text/layers/0/gdn/value":{"parts":[{"object":"weight/000000","range":[20971520,52428800]}]},
 "text/layers/0/gdn/z":{"parts":[{"object":"weight/000000","range":[52428800,83886080]}]},
 ...}
```
判读：三层寻址 —— `语义名 → object(weight/NNNNNN) → [range 字节区间]`。一个 object 内可塞多个张量。tensor 自身 **无 name 字段（0 个）**。

---

## E-07 模型身份：config 全文（本地）

```
metadata.name   = huihui-qwen3.8-27b-abliterated-swift15-gsq-rco-iq2s
provenance      = { converter: ninfer-v3, recipe: qwen3_8_27b_gguf,
                    sources.base: D:\Ab1-Swift\base (已删除),
                    sources.gguf: D:\Ab1-Swift\src\huihui-swift15-iq2s-mtp.gguf (已删除),
                    sources.vision: D:\Ab1-Swift\src\mmproj-model-bf16.gguf (已删除),
                    ranking: D:\Ab1-Swift\engine\tools\freq_corpus\fixtures\ranking\ranking.train.counts.i64 }
architectures   = ["Qwen3_5ForCausalLM"]
model_type      = "qwen3_5_text"
hidden_size 5120  vocab_size 248320  num_hidden_layers 64  intermediate_size 17408
max_position_embeddings 262144  tie_word_embeddings false  rms_norm_eps 1e-06
num_attention_heads 24  num_key_value_heads 4  head_dim 256
layer_types     = 48×linear_attention + 16×full_attention（每 4 层一个 full）
rope_parameters = { rope_theta 1e7, partial_rotary_factor 0.25, mrope_section [11,11,10] }
linear_num_key_heads 16  linear_key_head_dim 128
linear_num_value_heads 48  linear_value_head_dim 128  linear_conv_kernel_dim 4
vision.config   = qwen3_5_vision, depth 27, hidden 1152, intermediate 4304, num_heads 16,
                  patch_size 16, temporal_patch_size 2, spatial_merge_size 2, num_position_embeddings 2304
mtp.config      = architectures ["Qwen3_5MTP"]
resources       = tokenizer.json(12809320) / tokenizer_config.json(17928) /
                  chat_template.jinja(9712) / generation_config.json(202) /
                  vision/preprocessor_config.json(390) / vision/video_preprocessor_config.json(385)
```

---

## E-08 模型身份：上游官方 config（外部，来源 URL）

**来源**：`https://hf-mirror.com/Qwen/Qwen3.8-27B/raw/main/config.json`（HTTP 200）

```
architectures           = ["Qwen3_5ForConditionalGeneration"]
model_type              = "qwen3_5"
transformers_version    = "5.8.0.dev0"
text_config.model_type  = "qwen3_5_text"
hidden_size 5120  num_hidden_layers 64  vocab_size 248320  intermediate_size 17408
num_attention_heads 24  num_key_value_heads 4  head_dim 256
full_attention_interval 4  → layer_types 48 linear + 16 full（顺序与本地一致）
linear_num_key_heads 16  linear_key_head_dim 128  linear_num_value_heads 48
linear_value_head_dim 128  linear_conv_kernel_dim 4
mrope_section [11,11,10]  rope_theta 1e7  partial_rotary_factor 0.25
mtp_num_hidden_layers 1  mamba_ssm_dtype float32  attn_output_gate true  output_gate_type swish
vision_config: depth 27, hidden_size 1152, intermediate_size 4304, num_heads 16,
               patch_size 16, spatial_merge_size 2, temporal_patch_size 2,
               num_position_embeddings 2304, out_hidden_size 5120
image_token_id 248056  video_token_id 248057
```
**判定**：与本地 §E-07 逐项吻合 → 本地 `.ninfer` = `Qwen/Qwen3.8-27B` 的 abliterated + IQ2_S 量化版。
`Qwen3_5*` 是 **transformers 实现类名**，非模型版本号。`huihui-ai/Qwen3.8-27B-abliterated` 直取返回 401（需登录），不影响判定。

---

## E-09 训练环境：全部缺失

**命令**
```powershell
where.exe python; where.exe python3; where.exe conda; where.exe uv; where.exe nvcc; where.exe cl; where.exe wsl
Test-Path "C:\Program Files\Microsoft Visual Studio"; Test-Path "C:\Program Files\NVIDIA GPU Computing Toolkit"
```

**原始输出**
```
python  → C:\Users\Administrator\AppData\Local\Microsoft\WindowsApps\python.exe   （商店别名，调用 exit 1）
python3 → 同上别名
conda / uv / nvcc / cl / wsl → 全部 CommandNotFound
C:\Program Files\Microsoft Visual Studio          → 不存在
C:\Program Files\NVIDIA GPU Computing Toolkit     → 不存在
```
嵌入式 Python：`runtime\python\python.exe` 存在，**Python 3.12.8**（35 文件 / 21.4 MB，含 `python312._pth`，无 site-packages）；实测曾成功执行探针脚本，随后同路径 `Test-Path` 返回 False（云盘占位）。

**现有推理栈（可用）**
```
engines\sm86\infer-serve.exe   820,153,856 B (782.2 MiB)   覆盖 RTX 30
engines\sm89\infer-serve.exe   801,324,544 B (764.2 MiB)   覆盖 RTX 40
engines\sm120a\infer-serve.exe 710,338,048 B (677.4 MiB)   覆盖 RTX 50 / Blackwell
runtime\ 13 个 DLL（cublas64_13 / cublasLt64_13 / cudart64_13 / ffmpeg 5 / libcurl / VC++ 4）
launcher.py (UI :8720) · gateway\chat_gateway.py (:8081→:8080) · mcp_server.py (5 工具)
```

---

## E-10 网络：模型站点与镜像可达，pypi.org / github 不可达

**命令**
```powershell
foreach($u in @(...)){ Invoke-WebRequest -Uri $u -Method Head -TimeoutSec 12 -UseBasicParsing }
```

**原始输出**
```
https://huggingface.co                     → 200 (851 ms)
https://hf-mirror.com                      → 200 (283 ms)
https://www.modelscope.cn                  → 200 (230 ms)
https://mirrors.aliyun.com/pypi/simple/    → 200 (112 ms)
https://pypi.org/simple/                   → FAIL  timeout 12s

web_fetch https://github.com/...                → Error: hostname resolves to a non-public IP address
web_fetch https://raw.githubusercontent.com/... → Error: hostname resolves to a non-public IP address
```

---

## E-11 torch wheel：cu128 / cu130 均含 cp312 win_amd64

**来源（外部索引，实测 HTTP 200）**
- `https://download.pytorch.org/whl/cu128/torch/` → cp312/win_amd64 存在：2.7.0 / 2.7.1 / 2.8.0 / 2.9.0 / 2.9.1 / 2.10.0 / 2.11.0
- `https://download.pytorch.org/whl/cu130/torch/` → cp312/win_amd64 存在：2.9.0 / 2.9.1 / 2.10.0 / 2.11.0 / 2.12.0 / 2.12.1 / 2.13.0 / 2.14.0 / 2.14.1

---

## E-12 bitsandbytes：Windows 轮子连续提供到 0.50.2

**来源**：`https://mirrors.aliyun.com/pypi/simple/bitsandbytes/`（HTTP 200）
`win_amd64` 轮子：0.43.0 / 0.43.1 / 0.43.2 / 0.43.3 / 0.44.0 / 0.44.1 / 0.45.0 / 0.45.1 / 0.45.2 / 0.45.3 / 0.45.4 / 0.45.5 / 0.46.0 / 0.46.1 / 0.47.0 / 0.48.0 / 0.48.1 / 0.48.2 / 0.49.0 / 0.49.1 / 0.49.2 / **0.50.0 / 0.50.1 / 0.50.2**
Blackwell 上历史有 `libbitsandbytes_cuda128.dll` 缺失类报错 → 取 ≥0.48。

---

## E-13 FlashAttention：sm120 Windows 预编译仅 5 组版本组合

**来源**：`https://hf-mirror.com/axiomofmind/flash-attention-windows-wheel-blackwell/raw/main/README.md`（HTTP 200）
```
py3.11 + torch2.9.1 + cu128 → cp311, sm120
py3.11 + torch2.10   + cu130 → cp311, sm120
py3.11 + torch2.11   + cu130 → cp311, sm120
py3.12 + torch2.11   + cu130 → cp312, sm120     ← 本机唯一可行档
py3.13 + torch2.10   + cu130 → cp313, sm120
```
flash_attn 版本 2.8.4。本机无 MSVC → **不能现场编译，只能吃预编译轮子，版本必须锁死**。

---

## E-14 失败路径记录

| 项 | 结果 | 原因 |
|---|---|---|
| 派 subagent 拉上游支持矩阵 | 失败，无回执 | 该后台 subagent 中途失败；改主线程自查，§E-08/E-11/E-12/E-13 均为替代产出 |
| 直接读 `.ninfer` 反解 bf16 | 不成立 | 99.5% 体量为量化块 |
| `D:\Ab1-Swift` 原始转换工作区 | 不存在 | 已删除；provenance 记录的 base/gguf/vision/ranking 四路径全失效 |
| 嵌入式 Python 作训练解释器 | 不采用 | 无 site-packages + 路径间歇不可见 |
| 连续读同一 `.ninfer` | 间歇失败 | 云盘占位符；`Test-Path` 在 6 次内皆为 False，`-Recurse` 同时可列出 → 需重试或换路径解析 |
