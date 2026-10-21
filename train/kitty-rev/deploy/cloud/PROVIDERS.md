# 云主机选型与下单清单（为 27B QLoRA 一条龙）

> 需求画像：单卡 ≥24 GB 显存、≥150 GB 可用盘（基座 52 G + merged 54 G + .ninfer 16 G）、
> 能跑 Ubuntu 22.04 + CUDA 12.x + PyTorch 2.4~2.6、按小时计费、跑完即删。
> 全流程实际占用：**约 10–12 小时**（拉基座 10–20 min + 冒烟 30 min + 3 epoch 6–10 h + 合并 40 min + 转换 5 min）。

---

## 1 首选：AutoDL（国内，最省事）

| 项 | 值 |
|---|---|
| 机型 | **RTX 4090 24 GB**（单卡） |
| 参考价 | **¥1.5–2.3 / 小时**（不同地区/时段浮动，下单页为准） |
| 镜像 | `PyTorch 2.5.0` / `Python 3.12` / `Ubuntu 22.04` / `CUDA 12.4` |
| 系统盘 | 30 GB（默认，装环境够） |
| **数据盘** | **200 GB**（¥0.4–0.6/G/月，按天折算约 ¥3–4；**必须扩，否则 base+merged 装不下**） |
| 网络 | 国内直连 hf-mirror 快，52 GiB 基座约 10–20 min |
| 成本估算 | 12 h × ¥2 + 数据盘 ¥4 ≈ **¥28** |

**为什么选它**：国内付款/发票/带宽都顺，hf-mirror 直连，4090 24G 正好卡在 27B 4bit（12.6 GiB）+ ctx 2048 的安全区，
不需要 offload；跑完直接关机销毁。

### 下单后操作（AutoDL 特有路径）

```bash
# ① 数据都放数据盘，避免撑爆系统盘
cd /root/autodl-tmp
export HF_HOME=/root/autodl-tmp/hf

# ② 上传 bundle（本地执行）
#    scp -P <端口> kitty-rev-bundle-*.tar.gz root@<host>:/root/autodl-tmp/

# ③ 解包
mkdir -p kitty-rev && tar -xzf kitty-rev-bundle-*.tar.gz -C kitty-rev

# ④ 装环境（镜像自带 torch 2.5 + cu124，就锁 cu124 索引，避免重下 torch）
cd kitty-rev/cloud
TORCH_INDEX=https://download.pytorch.org/whl/cu124 bash setup.sh
# 若镜像 torch 已是 2.5.0+cu124，可先 python -c "import torch;print(torch.__version__)" 确认，
# 再手动只装训练栈：pip install "transformers>=5.8" peft trl accelerate datasets bitsandbytes

# ⑤ 一条龙
cd /root/autodl-tmp/kitty-rev
export HF_ENDPOINT=https://hf-mirror.com HF_HOME=/root/autodl-tmp/hf
ROOT=/root/autodl-tmp/kitty-rev bash cloud/run_all.sh smoke
ROOT=/root/autodl-tmp/kitty-rev bash cloud/run_all.sh full
ROOT=/root/autodl-tmp/kitty-rev bash cloud/run_all.sh merge
```

注意：AutoDL 关机后数据盘保留、GPU 计费停止；`.ninfer`（16 G）下来后就可以销毁实例。

---

## 1.5 4090 租罄时的同档替代：RTX 3090 24G（**可用，判据不变**）

| 项 | 3090 | 4090 | 差异对训练的影响 |
|---|---|---|---|
| 显存 | 24 GB GDDR6X | 24 GB GDDR6X | **一样**，27B 4bit（12.6 GiB）+ ctx2048 都能装 |
| 架构 | Ampere sm_86 | Ada sm_89 | 都支持 bf16 / bnb 4bit；4090 多 FP8（QLoRA 用不到） |
| 显存带宽 | ~936 GB/s | ~1008 GB/s | 差 7%，不是瓶颈 |
| 训练吞吐（QLoRA 实测经验） | 约为 4090 的 **55–65%** | 100% | 3 epoch 从 6–10 h → **10–16 h** |
| 参考价 | **¥0.9–1.5 /h** | ¥1.5–2.3 /h | 单位算力价格接近，**总成本基本一样甚至更低** |

**结论：3090 完全可用**。唯一代价是墙钟时间约 ×1.6–1.8，钱不一定多花。

### 3090 上的参数微调（省时间）

```bash
# ctx 从 2048 降到 1536：激活显存更小、每步更快，3908 条样本里 99% 的长度 < 1536
python kitty-rev/scripts/train_kitty.py --size 27b --ctx 1536 --bs 1 --ga 16 --all-gpu   --data kitty-rev/data/large-mix/train.jsonl --eval-data kitty-rev/data/large-mix/eval.jsonl
```

镜像选 **PyTorch 2.5.0 + CUDA 12.1（或 12.4）**；Ampere 上 bnb 4bit、bf16、SDPA 全部原生支持，
**不要**装 flash-attn（可选且编译麻烦，SDPA 够快）。

### 下单避坑

```text
[ ] 选"按量/独占"，不要"抢占/中断"（跑 12 小时被回收会前功尽弃）
[ ] 确认是 24 GB 版本（3090 有 24G 与少量 12G 改版，别选错）
[ ] 数据盘 200 GB（同 4090 的理由：base 52 + merged 54 + ninfer 16）
```

---

## 1.6 如果 3090 也没了：同档替代排序

| 顺位 | 机型 | 24G 档 | 相对速度 | 备注 |
|---|---|---|---|---|
| 1 | **4090D 24G** | ✓ | ≈4090 的 90% | 国内特供版，AutoDL 上偶有货 |
| 2 | **3090 Ti 24G** | ✓ | ≈4090 的 70% | 功耗高，价格略高于 3090 |
| 3 | **A5000 24G** | ✓ | ≈4090 的 55% | 专业卡，稳定但贵 |
| 4 | **L40S 48G** | 48G | ≈4090 的 85% | 显存翻倍，可上 ctx 4096，价格高 |
| 5 | **A100 40G** | 40G | ≈4090 的 110%（大 batch 更明显） | 最稳，最贵 |
| ✗ | L4 / A10 24G | ✓ | ≈4090 的 30–40% | 带宽太低，3 epoch 要 20 h+，不推荐 |

---

## 2 备选：阿里云 PAI-DSW / ECS gn7i

| 项 | 值 |
|---|---|
| 机型 | `ecs.gn7i-c16g1.4xlarge`（A10 24 GB）或 PAI-DSW 的 A10 规格 |
| 参考价 | 按量 **¥9–14 / 小时**（A10 比 4090 慢约 40%） |
| 优点 | 企业发票、VPC、与 OSS 直连；有免费试用额度 |
| 缺点 | 贵 5 倍左右；A10 显存带宽低，训练时间约 1.5–2 倍 |
| 适用 | 需要正规发票报销、或已有阿里云账号余额 |

---

## 3 备选：海外按需（RunPod / Vast.ai）

| 平台 | 机型 | 参考价 | 备注 |
|---|---|---|---|
| RunPod | RTX 4090 24G | **$0.34–0.69 /h**（≈¥2.5–5） | 稳定，社区镜像多；需外卡 |
| Vast.ai | RTX 4090 24G | $0.13–0.50 /h | 更便宜但为个人宿主，随时可能被回收；**跑 10 小时的任务不推荐抢断型** |
| Lambda | A100 40G | $1.29–1.79 /h | 贵，适合一次跑完不折腾 |

海外机拉 hf-mirror 反而慢，建议改回 `HF_ENDPOINT=https://huggingface.co`（或保留镜像，二选一测速）。

---

## 4 下单前自检清单

```text
[ ] 显存 ≥24 GB（不要买 16 GB 的 4080/A4000——27B 4bit 12.6 GiB 放不下就是白跑）
[ ] 数据盘 ≥150 GB（base 52 + merged 54 + ninfer 16，峰值 122 GB）
[ ] 镜像 CUDA 12.x + PyTorch 2.4~2.6（不要 2.0/2.1，transformers 5.x 要新 torch）
[ ] 按小时计费 + 随时销毁（不要包月）
[ ] 能 ssh + scp（要传 17 MB bundle、下 16 GB 制品）
[ ] 区域靠近自己（AutoDL 选西北/内蒙，国内下载快）
```

---

## 5 一句话结论

```text
首选 AutoDL RTX 4090 24G + 200G 数据盘 + PyTorch 2.5.0/cu124 镜像，全程约 ¥28、12 小时。
它正好落在"27B 4bit 不需要 offload"的甜点上，也是本机 12 GB 试穿 8 条路径后唯一省心的出口。
```
