# PENDING — MTP 头拼装（等训练完成后再执行）

> 状态：**暂停待执行**（2026-10-27 21:44 操作者要求：先不拼装，训练完再做）
> 脚本已就绪，缓存已留，训练完直接跑即可。

---

## 0 为什么现在不做

MTP 头必须拼到**最终要用的那份权重**上。训练还没开始，拼到 `OxCoder-9B` 原权重上没有意义：
训练产出的 adapter 要 merge 出新权重 → MTP 得拼到 **merged 结果**上，不是原基座。

```
现在:  OxCoder-9B (760 张量, 无 MTP)
          ↓ SFT/LoRA 训练
       adapter
          ↓ merge
       merged 权重  ← ★ MTP 要拼在这里
          ↓ attach_mtp
       merged + MTP (775 张量)
          ↓ convert --components text,mtp
       .ninfer (带投机解码)
```

---

## 1 训练完成后的一键执行

```powershell
# 前置：训练产出的 merged 权重已就位（路径按实际改）
$MERGED = "train\lines\9b-oxcoder\models\merged-v1"          # ← 改这里

# ① 拼 MTP（脚本支持 --src 指向任意同构 Qwen3.5-9B 检查点）
python train\lines\_shared\scripts\attach_mtp.py --src $MERGED --out "train\lines\9b-oxcoder\models\merged-v1-mtp"

# ② 校验（要求 mtp_tensors == 15）
python train\lines\_shared\scripts\attach_mtp.py --verify-only --out "train\lines\9b-oxcoder\models\merged-v1-mtp"

# ③ 带 MTP 转换（论文级 GSQ 量化）
train\lines\_shared\tools\ninfer-master\.venv-convert\Scripts\python.exe train\lines\27b-kittyrev\quant\run_convert_gsq.py `
  --model "train\lines\9b-oxcoder\models\merged-v1-mtp" `
  --recipe qwen3_5_9b_gsq `
  --components text,mtp `
  --device cuda --rows-per-chunk 512 `
  --name oxcoder-9b-mtp-gsq `
  --out "train\lines\9b-oxcoder\models\oxcoder-9b-GSQ-mtp.ninfer"

# ④ 引擎侧开投机解码
#    ninfer-csunx\config\engine.json:
#      modelFile  → oxcoder-9b-GSQ-mtp.ninfer
#    启动参数: --spec mtp --draft-tokens 3
```

> `attach_mtp.py` 当前 `--src` 默认指向 `train/lines/9b-oxcoder/models/OxCoder-9B`；训练后请用 `--src` 显式指到 merged 目录。

---

## 2 已就绪的资源

| 资源 | 路径 | 说明 |
|---|---|---|
| **MTP 权重（已落盘）** | `train/lines/9b-oxcoder/models/mtp/qwen3.5-9b-mtp.safetensors` | **464 MB / 15 张量 / 全 bf16**，2026-10-27 21:51 抽取完成 |
| MTP 清单 | `train/lines/9b-oxcoder/models/mtp/qwen3.5-9b-mtp.json` | 张量名 + 形状 + dtype + 来源 |
| 拼装脚本 | `train/lines/_shared/scripts/attach_mtp.py` | `--src <merged>` 拼装；`--extract-only` 重抽；`--verify-only` 校验 |
| 官方 9B 分片缓存 | `~/.cache/huggingface/hub/models--Qwen--Qwen3.5-9B` | 已下部分保留，重抽可续传 |
| 转换入口（含 GSQ） | `train/lines/27b-kittyrev/quant/run_convert_gsq.py` | 支持 `--components text,mtp` |

**训练后拼装不再需要联网**：`attach_mtp.py` 默认读 `train/lines/9b-oxcoder/models/mtp/qwen3.5-9b-mtp.safetensors`，只有本地文件缺失才回退下载。

### 已落盘的 15 个张量（形状已核，与 OxCoder-9B 架构逐项对齐）

```text
mtp.fc.weight                          [4096, 8192]      hidden→2×hidden（hidden+embedding 双输入）
mtp.pre_fc_norm_hidden.weight          [4096]
mtp.pre_fc_norm_embedding.weight       [4096]
mtp.norm.weight                        [4096]
mtp.layers.0.input_layernorm.weight    [4096]
mtp.layers.0.post_attention_layernorm.weight [4096]
mtp.layers.0.self_attn.q_proj.weight   [8192, 4096]      16 heads×256×2（含 output gate）
mtp.layers.0.self_attn.k_proj.weight   [1024, 4096]      4 kv heads×256
mtp.layers.0.self_attn.v_proj.weight   [1024, 4096]
mtp.layers.0.self_attn.o_proj.weight   [4096, 4096]
mtp.layers.0.self_attn.q_norm.weight   [256]             head_dim
mtp.layers.0.self_attn.k_norm.weight   [256]
mtp.layers.0.mlp.gate_proj.weight      [12288, 4096]     intermediate 12288
mtp.layers.0.mlp.up_proj.weight        [12288, 4096]
mtp.layers.0.mlp.down_proj.weight      [4096, 12288]
```
全部 `bfloat16`，与 OxCoder-9B 的 hidden 4096 / 16 heads / 4 kv / head_dim 256 / intermediate 12288 **逐项吻合**。

---

## 3 技术依据（已完成核验，勿重复验证）

| 项 | 结论 |
|---|---|
| OxCoder-9B 是否声明 MTP | ✅ `text_config.mtp_num_hidden_layers = 1` |
| OxCoder-9B 是否带 MTP 权重 | ❌ 760 张量里 mtp = 0 |
| 官方 Qwen3.5-9B 是否带 | ✅ 775 张量，15 个 `mtp.*` |
| 同构性 | ✅ layers 32 / hidden 4096 / vocab 248320 / heads 16 / kv 4 / head_dim 256，全项一致 |
| transformers 是否实例化 MTP | ❌ `AutoModelForCausalLM.from_config` 出 427 参数，MTP = 0 → **不能靠 transformers 训/加载，只能靠拼装** |
| ninfer 是否吃 MTP | ✅ `--spec mtp --draft-tokens 3`；27B 的 `.ninfer` 有独立 `mtp` 组件（arch=`Qwen3_5MTP`） |
| 27B 的 MTP 怎么来的 | `provenance.sources.gguf = gguf/v6-mtp-spliced.gguf` → 也是拼接路，9B 照做 |

15 个 `mtp.*` 张量：
```
mtp.fc.weight
mtp.pre_fc_norm_hidden.weight
mtp.pre_fc_norm_embedding.weight
mtp.norm.weight
mtp.layers.0.input_layernorm.weight
mtp.layers.0.post_attention_layernorm.weight
mtp.layers.0.self_attn.{q,k,v,o}_proj.weight
mtp.layers.0.self_attn.{q,k}_norm.weight
mtp.layers.0.mlp.{gate,up,down}_proj.weight
```

---

## 4 拼装后的风险与判定

| 风险 | 判据 | 对策 |
|---|---|---|
| **投机解码接受率未知** | 迁移的 MTP 是官方主干联合训过的，训练后的主干 hidden 分布已偏 → 接受率可能低于官方 | 转换后看引擎日志的 accept_rate；<30% 则走补训 |
| 补训 MTP | 冻结主干、只训 1 层 MTP，用 SFT 数据 | 需自写 hidden-state 采集 hook（transformers 没实现 MTP forward） |
| `--components text,mtp` 对 safetensors 路是否生效 | 27B 走的是 GGUF 拼接 | 若报错，改走 GGUF：先转 bf16 GGUF → 拼 MTP → `--source gguf` |

---

## 5 恢复执行检查单

```text
□ merged 权重已产出且 config.json 的 architectures 正确
□ attach_mtp.py --src <merged> 跑通，verify-only 显示 mtp_tensors = 15
□ convert 产物 > 5 GiB，且 header 的 components 含 mtp
□ 引擎启动带 --spec mtp --draft-tokens 3，/v1/models 200
□ 单轮推理 finish=stop（非 error/截断）
□ 记录 accept_rate（决定是否需要补训 MTP）
```
