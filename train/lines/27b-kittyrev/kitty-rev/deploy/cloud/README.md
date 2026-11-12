# 云端 24GB 跑 27B 后训练：上传包与操作手册

> 目标：把本项目的 27B QLoRA（数据 `data/large-mix`，3908 条）在 24GB 卡上跑通，回炉成 `.ninfer`。
> 本包**不含权重**（基座在云端现拉，比上传 52 GiB 快一个数量级）。

---

## 1 租什么卡

| 方案 | 显存 | 参考价 | 27B QLoRA 100 步 | 3 epoch（3908 条） | 备注 |
|---|---|---|---|---|---|
| RTX 4090 / 5090 | 24 GB | ¥1.5–3 /h | 20–40 min | 6–10 h | **性价比最高**，够 4bit 全量驻卡 |
| A100 40G | 40 GB | ¥6–12 /h | 15–25 min | 4–7 h | ctx 可上 4096，更稳 |
| L40S 48G | 48 GB | ¥8–15 /h | 15–25 min | 4–7 h | 同上 |

**镜像选**：Ubuntu 22.04 + CUDA 12.x + PyTorch 2.3~2.6（AutoDL / 阿里云 PAI / RunPod / Vast 都有现成的）。
显存判据：`nvidia-smi` 显示 ≥24 GB 且空闲 ≥22 GB。

---

## 2 上传与初始化（5 分钟）

```bash
# ① 上传（本地执行；bundle 由 deploy/make_bundle.sh 生成，约 20–60 MB）
scp -P <port> kitty-rev-bundle-*.tar.gz root@<host>:/root/

# ② 解包
ssh -p <port> root@<host>
mkdir -p ~/kitty-rev && tar -xzf kitty-rev-bundle-*.tar.gz -C ~/kitty-rev

# ③ 装环境（cu121；若镜像是 cu124 用 TORCH_INDEX 覆盖）
cd ~/kitty-rev/cloud && bash setup.sh
# 判据：最后打印 SETUP_OK，且 vram ≥ 24 GiB
```

`setup.sh` 会装：torch(cu121) + transformers≥5.8 + peft + trl + accelerate + datasets + bitsandbytes，
并自检 `torch.cuda.get_device_capability` 与显存。

---

## 3 一条龙（推荐顺序）

```bash
cd ~/kitty-rev
export HF_ENDPOINT=https://hf-mirror.com     # 国内机器必设；海外机器可去掉

# ① 冒烟 100 步（先证链路：拉基座 → 数据体检 → 100 步 → 看 loss）
bash cloud/run_all.sh smoke

# 判据（看到这些再往下走）
#   [base] done ...                 ← 52 GiB 拉完
#   VERDICT: PASS                  ← 数据质检
#   {'loss': ...} 逐步下降         ← 训练真的在学
#   DONE: smoke

# ② 正式训练（3 epoch）
bash cloud/run_all.sh full

# ③ 合并 + 回炉 + 结构自检
bash cloud/run_all.sh merge
# 产出：~/kitty-rev/merged/Qwen3.8-27B-kittyrev（54 GiB）
#       ~/kitty-rev/ninfer/qwen3_8_27b_kittyrev.ninfer（≈16 GiB）
```

---

## 4 训练参数（`run_all.sh` 里的默认值，24GB 实测安全区）

```text
--size 27b --ctx 2048 --bs 1 --ga 16 --all-gpu     # 有效 batch 16
LoRA r=16 alpha=32 targets=q/k/v/o/gate/up/down     # 只挂 7 个 Linear（红线）
4bit NF4 + double quant + gradient checkpointing
optim paged_adamw_8bit   lr 2e-4   cosine   warmup 10
```

OOM 时的退让顺序：`ctx 2048→1536→1024` → `ga 16→32` → `bs 1 保持`。
不要动 `--all-gpu`（24GB 上不该走 offload，offload 是 12GB 才需要）。

---

## 5 下机与回传

```bash
# 只回传 adapter（≈100–200 MB）和 .ninfer（≈16 GiB），不要回传 merged（54 GiB）
scp -P <port> root@<host>:~/kitty-rev/out/adapter/* ./out-adapter/
scp -P <port> root@<host>:~/kitty-rev/ninfer/qwen3_8_27b_kittyrev.ninfer ./

# 本地部署（工作区内）
copy qwen3_8_27b_kittyrev.ninfer D:\BaiduNetdiskDownload\Local-AI\train\ninfer\
# 旧制品先改名 .bak，再起引擎验证 /v1/models 200 + 一次真实推理
```

---

## 6 常见失败与处置

| 现象 | 原因 | 处置 |
|---|---|---|
| `CUDA out of memory` | ctx 太大或桌面占用 | 按 §4 退让顺序降参 |
| `transformers` 认不出 `Qwen3_5*` | 版本 < 5.8 | `pip install -U "transformers>=5.8"` |
| bnb 报 `no kernel image` | 装了 CPU 版 torch | 用 cu121 index 重装 torch |
| 拉基座 404 | 镜像没设 | `export HF_ENDPOINT=https://hf-mirror.com` |
| `merge` 内存不足 | 机器 RAM < 64 GiB | 用 A100 40G 机型，或分片 merge |
| converter 报 `short source read` | 在 Windows 上跑 | 云端是 Linux，没有该问题 |

---

## 7 本包内容清单

```text
kitty-rev/scripts/        训练/数据/校验脚本（train_kitty.py 已含 27B --all-gpu 路径）
kitty-rev/eval/           行为判据集（eval_kitty.py + bench 清单）
kitty-rev/data/large/     自有数据 train 2736 / eval 304 / dpo 48
kitty-rev/data/large-mix/ 混入开源推理链后的 3908 条（训练默认用这份）
kitty-rev/data/reasoning/ 开源推理链原始样本（NuminaMath / OpenThoughts / ToolACE / LIMO）
kitty-rev/contracts/      kitty 工具契约（64 工具 / 66 OP / 12 transition）
scripts/merge.py          合并 adapter（CPU）
scripts/fetch_base.py     基座下载（hf-mirror）
ninfer-master/            converter 源码（Linux 原生，无需 Windows 补丁）
cloud/setup.sh            环境初始化 + 自检
cloud/run_all.sh          smoke / full / merge 一条龙
```
