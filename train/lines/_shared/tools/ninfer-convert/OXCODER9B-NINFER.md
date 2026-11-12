# OxCoder-9B → .ninfer 制作链

> 状态（2026-10-26）：recipe 已接入并通过注册验证；**整链未实测**（缺 9B 权重下载与一次真实转换运行）。
> 上游来源：`Neroued/ninfer`（本地镜像 `ninfer-all-master/`）。本文件不替代 `docs/weight-conversion.md`。

## 1 结论

| 项 | 状态 |
|---|---|
| 公开网络有 OxCoder-9B 的 `.ninfer` | ✗ 无。`.ninfer` 为 v3 私有容器，公开流通仅 Qwen3.8-27B 系 |
| converter 是否支持 Qwen3.5 架构 | ✅ `tools/convert/qwen3_5.py` 覆盖 `Qwen3_5ForCausalLM`、`Qwen3_5ForConditionalGeneration`、两个 MoE 变体，含 Vision / MTP / DFlash |
| 是否缺 recipe | 原有 12 条全为 27B/35B/Flash_NEXT；**本次已补 `qwen3_5_9b` 与 `qwen3_5_9b_q8max`** |
| recipe 是否尺寸相关 | ✗ 不相关。`_dense_groupwise()` 几何来自 `model.parameters` 与 config，动态遍历 |

## 2 本次改动

`ninfer-all-master/tools/convert/official_recipes.py`

```python
def qwen3_5_9b(model, recipe, sources):
    _dense_groupwise(model, recipe, Q8)              # Q8 vocab, Q4 attn/gate/up, Q5 其余

def qwen3_5_9b_q8max(model, recipe, sources):
    _dense_groupwise(model, recipe, Q8, gate_up=Q8)  # 全 Q8

RECIPES = { ..., "qwen3_5_9b": qwen3_5_9b, "qwen3_5_9b_q8max": qwen3_5_9b_q8max, ... }
```

验证：`python -m py_compile` 通过；`from tools.convert.official_recipes import RECIPES` 返回 13 条含新增两条。

## 3 两条转换路线

```text
A) HF safetensors（推荐，OxCoder-9B 直接可下）
   HF 目录 --source quantized=<dir> --> tools.convert(--recipe qwen3_5_9b) --> .ninfer
   --components text   只要文本（无 vision 塔）

B) GGUF → .ninfer（省下载体量，但 9B 需先有混合精度 GGUF）
   --recipe qwen3_8_27b_gguf 不适用（该 recipe 硬校验 27B Dense 几何）
   9B 走 GGUF 需另加 gguf_blocks 变体；当前优先 A 路
```

## 4 metadata 目录（`--model` 只吃元数据，不吃权重）

```text
metadata-oxcoder9b\
├─ config.json                 # 必需（architectures 应为 Qwen3_5ForConditionalGeneration）
├─ generation_config.json      # 必需
├─ tokenizer.json              # 必需
├─ tokenizer_config.json       # 必需
├─ preprocessor_config.json    # 有 vision 组件时必需（--components text 可省）
└─ video_preprocessor_config.json
```

## 5 已知卡口与未验证项

1. **MTP 组件要求（最高风险）**：本机引擎启动曾报
   `Qwen3.5 config: missing component mtp`。若引擎对 Qwen3.5 家族强制要求 artifact 内含 `mtp` 组件，
   则无 MTP 头的 9B 转换产物会被拒绝加载。需实测；对策顺序：
   ① 先按 `--components text` 转换并试起引擎；
   ② 若报 missing mtp，改用带 MTP 头的检查点，或在 recipe 里 `--override` 注入空 MTP 组件；
   ③ 仍不行则回落到 GGUF 路线取同模型带 MTP 的 GGUF。
2. **Vision 组件来源**：`--components text` 时 artifact 无 vision，`--vision-cpu` 不可用；
   要多模态需从同模型 mmproj GGUF 取 vision 组件。
3. **磁盘占用**：`qwen3_5_9b` 约 6.0-6.3 GiB，`qwen3_5_9b_q8max` 约 9.6 GiB。
4. **转换时长**：未测。27B 级此前按小时计，9B 预估 15-40 分钟（CPU device、rows-per-chunk 512）。
5. **sm_120 构建**：converter 本身与 GPU 无关（`--device cpu`）；引擎侧已有
   `device profile nvidia-geforce-rtx-5070-ti-laptop-gpu-sm120: 51 routed keys`。

## 6 命令

```bat
REM 默认档（Q8 vocab / Q4 attn / Q5 其余）
train\lines\_shared\tools\ninfer-convert\convert-oxcoder9b.cmd

REM 全 Q8 高质量档
train\lines\_shared\tools\ninfer-convert\convert-oxcoder9b.cmd q8max
```

或直接调：

```bat
pushd train\lines\_shared\tools\ninfer-convert\ninfer-all-master
..\..\ninfer-master\.venv-convert\Scripts\python.exe -m tools.convert ^
  --model  train\lines\9b-oxcoder\models\metadata-oxcoder9b ^
  --recipe qwen3_5_9b ^
  --source quantized=train\lines\9b-oxcoder\models\OxCoder-9B ^
  --components text ^
  --device cpu --rows-per-chunk 512 ^
  --name oxcoder-9b --out train\lines\9b-oxcoder\models\oxcoder-9b-Q4Q5.ninfer
popd
```

## 7 验收判据

```text
① convert 退出码 0，产物存在且 > 5 GiB
② ninfer_model(action=switch, file=<新文件>) 可列出
③ 起引擎 → /v1/models 返回 200 且模型 id 正确
④ 单次推理 finish=stop，非 error / 非 max-tokens 截断
⑤ 若 ③④ 因 missing mtp 失败 → 记录该路径并转 §5.1 对策
```
