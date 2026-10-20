# 本地微调/后训练能力评估 · 备案包

- 备案号：`SHIYI-LOCALAI-MT-20261020`
- 时间跨度：2026-10-20 10:28 → 22:11（Asia/Shanghai）
- 评估对象：`D:\BaiduNetdiskDownload\Local-AI` 内的 NInfer 27B 推理栈
- 结论版本：第 4 版（含 Qwen3.8/3.5 类名误读的更正）
- 状态：**已收口**；4 轮追加分析，无未决项

---

## 1 一句话结论

**现部署的 `.ninfer` 不能直接微调；能做的方式是取 `Qwen/Qwen3.8-27B` bf16 基座做 LoRA/QLoRA，再转 GGUF → ninfer-v3 converter 回炉覆盖部署。本机硬件（RTX 5070 Ti Laptop 11.9 GB / 31.5 GB RAM）在 8B 级舒适、14B 贴边、27B 必须 offload。**

---

## 2 三条判定（速查）

| 问题 | 判定 | 一句话依据 |
|---|---|---|
| 硬件够不够 | ✓ 够 8B，△ 勉强 27B | 11.9 GB VRAM；27B 4-bit 权重 13.5 GB 已超卡 |
| 现 `.ninfer` 能否原地微调 | ✗ 不能 | 引擎 `infer-serve.exe` 只有前向，无训练图/优化器 |
| 现 `.ninfer` 能否反解成可训权重 | △ 能解，不划算 | 689 个量化张量占 12.75 GiB（99.5%），反量化为全模型近似 |
| 取上游基座重训能否闭环 | ✓ 能 | `Qwen3_5ForCausalLM` 有 transformers 侧支持，transformers ≥5.8 |
| 回炉（adapter→.ninfer）能否做 | △ 取决工具 | ninfer-v3 converter 本机已丢失，须从上游重取 |
| 本机现在能开跑吗 | ✗ 不能 | 无 Python/pip/uv/conda、无 nvcc、无 MSVC、无 WSL |

---

## 3 文件索引

| 文件 | 内容 | 谁看 |
|---|---|---|
| `01-评估报告.md` | 主报告全文（§0–§11），四轮分析原始产物 | 要完整推理链 |
| `02-EVIDENCE.md` | **证据链**：每条结论 ↔ 执行命令 ↔ 原始输出 | 复核/审计 |
| `03-FINDINGS.md` | 结构化判定表、路径记录（不可用路径+替代）、待办 | 决策 |
| `04-RUNBOOK.md` | 可执行落地命令全集（装环境→训练→合并→回炉） | 执行 |
| `05-MODEL-ID.md` | 模型身份核实：Qwen3.8 vs `Qwen3_5*` 类名，逐参数比对 | 排疑 |
| `probes\` | 8 个探针脚本（容器解析/config dump/bindings/解包器） | 复现 |
| `data\manifest.json` | 容器全量清单：1422 bindings + 733 无损 + 689 量化 + 格式直方图 | 数据处理 |
| `data\quantized.csv` | 689 个量化张量逐条（name/object/format/shape/bytes/offset） | 反量化用 |
| `SHA256SUMS.txt` | 全包哈希 | 完整性 |

---

## 4 关键读数（原始）

| 项 | 读数 |
|---|---|
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU，**11.9 GB**（注册表 `qwMemorySize`；WMI 报 4 GB 为 32 位截断，弃用） |
| 驱动 | 32.0.16.1742；算力档 sm_120a（Blackwell GB203） |
| iGPU | Intel(R) Graphics，驱动 32.0.101.8331 |
| CPU | Intel Core Ultra 7 270HX Plus，20 核 / 20 线程 |
| RAM | 31.5 GB |
| OS | Windows 11 专业版 10.0.22631 |
| 空盘 | C 122.0 / D 164.5 / E 326.3 / G 149.1 GB |
| 部署模型 | 4 个 `.ninfer`：9.55 / 8.87 / 7.13 / 7.13 GiB |
| 容器 | `NINFER` ver 768，json_len 352224，objects 1192，bindings **1422** |
| 权重构成 | 无损 733 个 = 0.06 GiB（0.5%）；量化 689 个 = **12.75 GiB（99.5%）** |
| 模型身份 | `Qwen/Qwen3.8-27B`（VL，64 层，H5120，V248320；48 linear + 16 full attention） |

---

## 5 复核方式（任何人拿到本包）

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\_research\微调能力-备案-20261020
# ① 校验完整性（UTF-8 读，逐条重算；当前已验证 verify_bad=0）
$bad=0
foreach($line in [System.IO.File]::ReadAllLines("$PWD\SHA256SUMS.txt",[System.Text.Encoding]::UTF8)){
  if(-not $line.Trim()){continue}
  $i=$line.IndexOf('  '); $exp=$line.Substring(0,$i); $rel=$line.Substring($i+2)
  $abs=Join-Path $PWD ($rel -replace '/','\')
  if(-not (Test-Path -LiteralPath $abs)){ "MISSING $rel"; $bad++; continue }
  if((Get-FileHash -LiteralPath $abs -Algorithm SHA256).Hash.ToLower() -ne $exp){ "MISMATCH $rel"; $bad++ }
}
"verify_bad=$bad"     # 期望 0

# ② 复现容器解析（只读，不落盘）
& .\probes\_probe_config.ps1 -Path "D:\BaiduNetdiskDownload\Local-AI\ninfer-27b-kv-stream-3arch-20261019\model\Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer"

# ③ 复现解包清单（-RawOnly 不导出张量）
& .\probes\ninfer-extract.ps1 -Ninfer "<上条同路径>" -OutDir .\recheck -RawOnly
# 期望输出：objects=1192  bindings=1422  lossless=733 (0.06 GiB)  quantized=689 (12.75 GiB)
```

> 注：`SHA256SUMS.txt` 为 UTF-8（无 BOM）编码，含中文文件名。用 `Get-Content`/`Set-Content -Encoding ASCII` 处理会打坏文件名，导致校验假失败。

---

## 6 已知环境坑（影响复现）

1. **工作区位于百度网盘同步目录**，实测同一路径反复出现「`Test-Path` False → `listdir` 空 → `-Recurse` 又能列出」的间歇不可见（`runtime\python\python.exe`、`model\*.ninfer`、`工具\inspect_ninfer.py` 均复现）。所有探针脚本已内置重试；跨轮复现可能需多次重试。
2. `github.com` / `raw.githubusercontent.com` DNS 解析到非公网 IP，**直连不可用**；HF 相关一律走 `hf-mirror.com`。
3. `pypi.org` 直连 12 s 超时；pip 必须显式 `-i https://mirrors.aliyun.com/pypi/simple/`。
4. 文件系统版本：`_research\` 下另有前序调研件（`0bserverx_*`、`obs_heretic.md`、`ista_gsq.md`、`bonsai.md` 等），属模型来源调研，非本备案包内容，仅此标注避免混淆。
