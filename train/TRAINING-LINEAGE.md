# TRAINING-LINEAGE — 训练血统与续训规约

> 目的：保证每一代训练的产物**可继续后训练**、可溯源、可回滚。
> 规则：数据集正在被持续优化，任何一次训练都必须锚定「当时的」数据版本。

---

## 0 铁律（每次训练前自检）

```text
① 数据必须打快照   train/data/versions/mix-*.YYYYMMDD-HHMMSS.jsonl + .sha256
                    数据集被改动后，旧版本从 versions/ 取，不依赖工作副本
② 产物必须是 adapter 或 bf16 merged，**不得只留 .ninfer**
                    .ninfer 是 v3 推理容器（量化块 + 索引），只有前向，不可训
③ merge 必须用 bf16 基座，不得用 4bit 基座
                    4bit 上算出的 LoRA 若在 4bit 权重上 merge，会在反量化误差上再叠一层
④ 每次训练写一条记录到本文件 §3，含数据 sha256 与超参
⑤ 转换 .ninfer 是单向操作，只在「确认不再续训」后做
```

---

## 1 续训的三种合法起点

| 起点 | 磁盘成本 | 适用场景 | 代价 |
|---|---|---|---|
| **A. adapter + 原基座（推荐保留）** | 173 MB | 只想保留能力、暂时不合并 | 推理时需 peft 加载，不能直接走 .ninfer |
| **B. bf16 merged 中间态** | +17.5 GB | 要在第一代成果上训第二代 LoRA | 占盘；但路径最干净，且可直接转 .ninfer |
| **C. 从原基座重训（数据合并）** | 0 | 数据优化幅度大、想避免代际漂移 | 丢失第一代的调参经验，需重跑 |

**不可用的路径**：在 `.ninfer` 上再训 —— 引擎只有前向，无训练图/优化器（`docs/06-posttraining-feasibility.md` §8 已实测确认）。

多代 adapter 也不能「叠加成一份权重」：PEFT 可以 load 多个 adapter 分别推理，但 `.ninfer` 只接受单一权重集，所以**最终必须 merge 成一份**。因此两代之间要么 merge-再训（B），要么重训（C）。

---

## 2 磁盘与显存预算（12 GB / 280 GB 实测）

```text
显存  9B 4bit QLoRA, ctx 2048, r=32, bf16 激活  →  实测 11.7 / 12.0 GiB（零余量）
      OOM 时的降级顺序：ctx 1536 → 从 targets 移除 in_proj_qkv → r=16

磁盘  基座 17.5 G + merged 17.5 G + 每代 adapter 0.17 G + 数据快照 <1 M
      当前 D 盘余 279 G，足够 3-4 代
```

---

## 3 训练记录

### 2026-10-27 01:0x — 第 1 代：RE SFT on OxCoder-9B

```text
基座        train/models/OxCoder-9B
            来源 OrionLLM/OxCoder-9B，sha256 d4fca682…fcc33b，17.53 GiB，760 tensors
架构        Qwen3_5ForConditionalGeneration，32 层（24 linear_attn + 8 full_attn）
            4096 hidden / 248320 vocab / vision 333 tensors / 无 MTP 张量
数据        train/data/versions/mix-re.20261027-011850.jsonl
            690 条 / 684,382 B
            sha256 440988f12623eea27cceef9ccff2fd48045a50a7cc738be600c511512878499a
            构成 forge 480（decision-chain / detour-trajectory / op-semantics / pe-structure）
                 + forge2 210
超参        stage=re → ctx 2048, r=32, alpha=64, lr 1e-4, 4 epoch, bs=1, ga=16
            约 172 optimizer steps，实测 ~22 s/step
LoRA 面     12 类模块，86,556,672 可训练参数（0.9115%）
            linear_attn: out_proj/in_proj_qkv/in_proj_z/in_proj_a/in_proj_b 各 24
            mlp: gate/up/down 各 32；full_attn: q/k/v/o 各 8
产物        train/out/oxcoder9b-re-full/final/   （adapter，r=32）
状态        ✅ 完成 2026-10-27 02:08（01:10 启动，58 分钟）
校验        496 张量（lora_A 248 / lora_B 248），lora_B 非零 248/248
            lora_B absmax 中位 0.004486 / max 0.052490 / min 0.002151
            （对比 30 步冒烟 0.00124，涨 3.6 倍 → 172 步确实生效）
            r=32 alpha=64；training_args.bin 已存，超参可追溯
缺口        loss 曲线未留存（stdout 被 grep 过滤 + save_strategy="no" 无 trainer_state）
副产品      train/out/oxcoder9b-re-full/checkpoint-132、checkpoint-176（各 353 MB，含 optimizer state）
            → checkpoint-176 = 第 4 epoch 末 = 完整终态，**可无缝续训**（optimizer 状态未丢）
              续训命令：--resume train/out/oxcoder9b-re-full/checkpoint-176
评估        未做 —— 按操作者要求，本次训练跑完即停，不自动接续
            待评估：拒率变化 / eval_re_extended(60条) / coding·RE·logic 三探针
环境坑      ① trl 1.16 无 warmup_ratio → warmup_steps=10
            ② SFTConfig 无 logging_dir → 删除
            ③ packing=True 时 Qwen3.5 linear_attn 需 causal_conv1d → packing=False
            ④ 显存实测 11.7/12.0 GiB，脚本预估 7.3 偏低
```

### 2026-10-27 02:33 — 第 2 代：joint（RE + NSFW，**中断 · 待续**）

```text
基座        train/models/OxCoder-9B（不从第 1 代 checkpoint 续，数据分布已大改）
数据        train/data/versions/final-joint.20261027-022747.jsonl
            2745 条（re 1647 / nsfw 1098）/ 2.79 M 字符
            sha256 53ff160d887baa92…（完整值见同目录 .sha256）
超参        stage=joint → ctx 2048, r=32, alpha=64, lr 6e-5, 3 epoch, bs=1, ga=16
            516 步，实测 42-55 s/步

中断        2026-10-27 04:49:22 — 系统 BSOD 0x0000001E (参数1 0xC0000005 内核访问违例)
            前兆 04:41:18 nvlddmkm ID=14（NVIDIA 驱动内部错误）
            dump  C:\Windows\Minidump\102726-13375-01.dmp
            诱因  显存贴顶 11,674/12,227 MiB + 满载 100% 连续 2h16m（笔记本散热边界）
进度        172 / 516 步（33%，epoch 1 完成）
损失曲线    step 5   loss 3.606  acc 0.4049
            step 165 loss 2.014  acc 0.6067
            step 170 loss 1.934  acc 0.6287     ← 单调改善，训练健康
保住        train/out/oxcoder9b-joint-v2/checkpoint-172/
            adapter 173 MB + optimizer.pt 73.9 MB → 可无损续训

恢复命令（操作者定时机；当前已被告知暂不启动）：
  train/.venv/Scripts/python.exe train/scripts/train_qlora9b.py \
    --base train/models/OxCoder-9B \
    --data train/data/final-joint.jsonl \
    --stage joint --lora-r 32 --lora-alpha 64 \
    --ctx 1792 --save-steps 50 \
    --resume train/out/oxcoder9b-joint-v2/checkpoint-172 \
    --out train/out/oxcoder9b-joint-v2

防丢进度    train_qlora9b.py 已加 --save-steps（默认 50，save_total_limit=3）
防再崩      ctx 2048→1792（显存 ~10.5 GiB，余 1.7 GiB）；关 GameViewer 虚拟显示器；
           电源计划改「平衡」；或回滚 NVIDIA 驱动 32.0.16.2101
```

### 已放弃的路线（记录原因，避免重走）

```text
Heretic/ARA 方向消融   帕累托悬崖：γ≤1 不生效（KL 0.046，拒率 100%）
                      γ=2 KL 0.50 拒率仍 100%；γ≥4 模型崩（KL 7.4-17）
                      9 个 trial 最好的有效点 KL 0.58 / 拒率 53%
SRA 概念引导谱残差化   残差化方向正确（cos 0.20→0.003，能量仅削 3.5%）
                      但 γ 扫描同样撞悬崖，无甜点
结论                   9B 上「先纯化底座再去 SFT」不成立；改为 SFT 数据层面直接重塑行为
```

---

## 4 下一次训练的接入方式

```text
若走 A（adapter 保留）：
  eval 时 --adapter train/out/oxcoder9b-re-full/final
  要接着训 → 先 merge 成 bf16（走 B）

若走 B（merge 后训）：
  1) merge bf16 基座 + 第 1 代 adapter → train/merged/oxcoder9b-gen1-bf16
  2) train_qlora9b.py --base train/merged/oxcoder9b-gen1-bf16 --data <新一代数据>
  3) 产物记入本文件 §3

若走 C（重训）：
  train_qlora9b.py --base train/models/OxCoder-9B --data <合并后数据>
```

每次训练前把 `train/data/*.jsonl` 快照到 `train/data/versions/` 并在 §3 记 sha256 —— 这是数据集持续优化时的唯一可靠锚点。
