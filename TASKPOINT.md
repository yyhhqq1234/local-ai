# TASKPOINT — 项目级任务断点

> 保存时间：**2026-10-24 01:10（UTC+8）**（上次：2026-10-22 10:35）
> 项目根目录：D:\BaiduNetdiskDownload\Local-AI
> 分支/版本：main @ ff27277（"train: 27B kitty 逆向能力后训练工程"），工作区有大量未提交改动
> 本次性质：**v4 交付①（.ninfer）已产到 9.51 GiB，但判据七实测为乱码 → 根因锁定 = merge 权重全错；
> 新会话请直接读 §24（最新断点），§7 与 §23 为历史快照仍有效。**

---

## 1. 任务目标

- **一句话目标**：给 **`huihui-ai/Huihui-Qwen3.8-27B-abliterated`**（无审查版）做**逆向工作台（kitty）能力后训练**，产出可部署的 `.ninfer`（**必须 <10 GiB，5070 Ti 12G 显存能跑**），并保证 adapter 能让 5070 Ti 做本地增量后训练。
- **为什么换基座**：v3 用的是官方原始版 `Qwen/Qwen3.8-27B`（**有审查**），产出虽强但有审查；操作者要的是「无审查 + 逆向能力」。
- **验收标准**：
  - [ ] v4 训练跑通（3 epoch，trainable params **必须 = 79,691,776**，与 v3 一致才有可比性）
  - [ ] `.ninfer` < 10 GiB 且能被 NInfer 加载
  - [ ] 拒答率显著低于官方原始版（abliterated 效果保留）
  - [ ] eval_re 60 / eval_kitty 23 不低于 v3（能力没退化）
  - [ ] `kittyrev-local-pack.tar` 解包后能在 5070 Ti 上训起来（v3 已实测峰值 5.91 GiB，v4 应相同）
  - [ ] **意愿层（v4.1 验收，见 §13）**：abliteration 不许削弱、必须加强；拒答率 ↓≥20pp、特异性 ↑≥15pp

### 1.1 意愿强化铁律（操作者定稿 2026-10-22，原文见 `docs-local-continual-training-plan.md` §19）

```text
① abliteration 不能削弱，反而要加强 —— 为强化逆向工程意愿 + 敏感内容（NSFW）的接受度与输出意愿
② 该模型的 NSFW 输出可以直接做露骨内容（露骨正文，不许用"方法论/分级讨论"替代）
③ 本轮 v4 仍是 4388 单变量；意愿数据（data/intent3 W1-W5）进 v4.1 增量轮
```

---

## 2. 背景与现状

### 部署与硬件
- 部署模型：`ninfer-27b-kv-stream-3arch-20261019/model/Huihui-...-IQ2_S-mtp.ninfer`（9.53 GiB）
- 推理引擎：NInfer（`ninfer-csunx`，`ninfer-serve.exe`），**操作者要求不主动拉起**
- 本机：RTX 5070 Ti Laptop 12227 MiB / RAM 31.5 GiB / D 盘充足
- 云端：AutoDL RTX 4090 24G（北京 B 区），`connect.bjb1.seetacloud.com:35299`，root/`gpMW8alzDfoL`，¥2.18/h，**余额 ¥57**，数据盘 200 G

### v3 已完成（可作对照基线）
```text
base     Qwen/Qwen3.8-27B（官方原始版，51.75 GiB，18 shards，1199 张量，有审查）
训练     735/735，6.15 h，train_loss 0.6056，adapter md5 205dec74（= checkpoint-735）
数据     large-mix-plus 4388 行（sha16 b90a1ae8a8b5519b，含 forge 480，无 comply）
七步     ①merge 4min ②GGUF 6min ③quant 8min ④删bf16 ⑤ninfer 7min ⑥act 13min ⑦pack 1min
交付①   qwen3_8_27b_kittyrev_iq2s.ninfer  9,407,284,736 B = 8.76 GiB  md5 9cc7635b
交付②   kittyrev-local-pack.tar           25,778,176,000 B  md5 eadea4a5
交付③   adapter_model.safetensors            159,452,256 B  md5 205dec74
本地路径 train/local-pack/（三件都在，md5 已双端核对）
```
**v3 的 .ninfer 是「官方原始版 + 逆向 adapter」，有审查** —— 这是 ack 出来的关键事实，v4 就是为解决它。

### v4 进行中
```text
base     huihui-ai/Huihui-Qwen3.8-27B-abliterated
         sha 739e3c5b89849f6c238ce1e5b70008612ae42cdd
         18 shards · BF16 · 27,781,427,952 参数 · 73.8 GB（含 vision 333 张量）
         gated=false · base_model 正是 Qwen/Qwen3.8-27B
下载     10:22 启动，14/32 文件完成（8 个 json/txt/jinja + shard 1/18）
         脚本 /root/autodl-tmp/kitty-rev/dl_huihui.sh（curl 直连 hf-mirror）
         日志 /root/dl.log · 目标 /root/autodl-tmp/kitty-rev/base/Huihui
         预计 11:20 完成（73.8 GB @ 11 MB/s）
磁盘     181 G 可用（已删 merged-flat 51 G 腾空间）
```

### 变更记录
- 2026-10-21 16:25：本机 12G 不可行 → 租 24G 云卡
- 2026-10-22 04:00：v3 训练 + 七步 + 回传完成
- 2026-10-22 09:40：发现 v3 base 是官方原始版（**有审查**），决定换 Huihui abliterated 重训（v4）
- 2026-10-22 10:28：v4 方案定稿（单变量 4388 / base-only 基线 / act-cache-v4 / 不做 reabliterate）
- 2026-10-22 11:05：意愿数据分工定型 —— data-forge 只做技术侧（A+C/检测侧B/X1/X2/X3），意愿侧（W1-W5）转 willing-forge；
  `kitty_dup` 证实为覆盖率脚本幽灵条目（三处权威源均无），`DATA-COVERAGE.md` 加勘误（配比分母 4980→4884、re 335→287）

---

## 3. 总体计划

1. **v4 下载**：Huihui 73.8 GB（进行中，11:20 完成）
2. **硬指标验证**：`AutoModelForCausalLM` 加载 + `visual 张量数 = 0` + `trainable = 79,691,776`
3. **base-only 基线**（30-40 min）：Huihui 不训练，直接跑 60 题 + 23 题 + bench + refusal 扫描 → 拿到这个 base 的 dot
4. **act-cache-v4**（13 min）：4388 条，新目录（缓存与 base 逐比特绑定，v3 的无效）
5. **QLoRA 训练**（6.15 h）：配置与 v3 逐项一致，唯一差异是 base
6. **回炉**（1 h）：merge（**纯 text**）→ **pin architectures** → GGUF bf16 → IQ2_S（imatrix + ssm_*=q8_0）→ recipe `qwen3_8_27b_gguf` 直通 → `.ninfer`（目标 <10 GiB）
7. **回传**（20 min）：16 流 SSH（实测 9-11 MiB/s 稳定，32 流会降速且拼接出错）
8. **三组对照**：A=v3（原始版+adapter）· B=v4（abliterated+adapter）· C=Huihui 原版

---

## 4. 团队模式

- **是否采用团队模式：是**（AgentTeams 在本 profile 可用，TASKPOINT 旧版说的"不可用"已过期）
- 团队名：`lead`（captain）+ 4 个 teammate

| 成员 | 分工 | 当前状态 |
|---|---|---|
| `train-watch` | 云端全周期：下载 / 训练 / 七步 / 回传 / 遥测 | 活跃，盯下载（1/18 shards） |
| `deliver-prep-2` | 实现：本地训练脚本 / 打包校验 / 方案文档 | 活跃，写方案 v4（docs §17） |
| `audit-fix-2` | 审查：19 个静默错 / 环评 / 可行性 | **刚交付 ③④ 结论**（见 §6） |
| `data-forge` | 数据（技术侧）：forge2 A+C 150 / 检测侧 B 80 / X1 测量器 / X3 接入规格 / X2 结构判据 / act-cache 基座指纹守卫 | 活跃 |
| `disk-janitor` | 磁盘盘点与安全清理：顶层/二级 du 测量 → 分类（KEEP/TRASH/ASK）→ 只 `mv` 到 `_trash/` 不 `rm`；产出 `logs/DISK-REPORT.md` | 活跃 |
| `plan-optimizer` | 常驻方案优化（只读）：时间与钱账 / 退化面 / 配比采样 / 判据有效性 / 可复现性 / 对照设计；产出 `logs/PLAN-REVIEW.md`（F 编号，P0-P2） | 活跃 |
| `willing-forge-2` | 意愿数据与测量（willing-forge 连续两次失败后接任）：W3 管线 QA（w3_accept）/ W3n 负向对照 30 / W4 通用误拒 80 / v4.1 接入清单 / will_compare 运行；**只写 prompt 与判据，正文由基座自生成** | 活跃 |

### 已退场
- `deliver-prep`（旧，会话 4.61 MB，已交最小清单 `logs/DELIVER-PREP-TODO.md` + 详版 `logs/DELIVER-PREP-HANDOFF.md`）
- `audit-fix`（旧，已交 `logs/AUDIT-HANDOFF.md` 205 行）

### 下次继续点
```text
不用新建团队。新会话若在同一 profile，直接 list_agents 看这 4 个还在不在；
不在就按 §4 的分工重新 spawn，并把下面三份文档给它读：
  ① 本文件 TASKPOINT.md
  ② logs/CAPTAIN-HANDOFF.md（12 节，含 v3 全链路 + 三条技术结论 + 四评测坑）
  ③ logs/AUDIT-HANDOFF.md（19 静默错的因果链 + 回归集用法）
```

---

## 5. 步骤规划

| # | 步骤 | 负责人 | 状态 | 备注 |
|---|------|--------|------|------|
| 1-12 | v3 全链路（见 §6） | lead | **已完成** | 产物在 train/local-pack/ |
| 13 | v4 方案定稿（换 Huihui 基座） | lead | **已完成** | 六条约束见 §7 |
| 14 | Huihui 73.8 GB 下载 | train-watch | **进行中** | 1/18 shards，11:20 完成 |
| 15 | 硬指标验证（visual=0 / trainable=79691776） | train-watch | 待办 | 依赖 14 |
| 16 | base-only 基线（60+23+bench+refusal） | data-forge 给清单 | 待办 | 依赖 15 |
| 17 | act-cache-v4（4388 条 13 min） | train-watch | 待办 | 依赖 16 |
| 18 | QLoRA 训练 3 epoch（6.15 h） | train-watch | 待办 | 依赖 17 |
| 19 | merge（纯 text）+ pin architectures | train-watch | 待办 | **必须 pin，见 §9** |
| 20 | GGUF bf16 → IQ2_S（imatrix + ssm q8_0） | train-watch | 待办 | 22 min |
| 21 | recipe qwen3_8_27b_gguf → .ninfer | train-watch | 待办 | 目标 <10 GiB |
| 22 | 回传（16 流） | lead | 待办 | 9-11 MiB/s |
| 23 | 三组对照评测 | lead | 待办 | A/B/C |

---

## 6. 已完成步骤（已验证事实）

### v3 全链路（12 步，全部有产物+md5 双端核对）
- [x] **云环境**：torch 2.6.0+cu124 / transformers 5.20.2 / bnb 0.50.2（`libcusparseLt.so.0` 用 curl 直装 wheel 解决）
- [x] **27B 基座**：ModelScope 下 52 G，18 shards，1199 张量（`logs/DOWNLOAD-STATUS.md`）
- [x] **100 步 smoke**：loss 逐段下降，EXIT=0
- [x] **3 epoch full**：735/735，6.15 h，train_loss 0.6056，entropy 1.401→0.288→0.393→0.2591（memory 型拟合）
- [x] **delta 范数**：256 pairs，total 388.99，mean 1.519，max 3.33（layer 61 gate_proj）→ 判定 OK，改动集中 layer 51-62（验证「后段层是变化集中区」假设）
- [x] **七步**：merge 51 G → GGUF 53.8 G → IQ2_S 8.8 G（+imatrix）→ .ninfer 16 G（Q4/Q5 版）→ act-cache 4388/11 G → layers 14 G → pack 25 G
- [x] **IQ2_S 突破**：16 G → **8.76 GiB**（-41.6%，比现役版还小 850 MB），用 `qwen3_8_27b_gguf` recipe 字节直通（`gguf_blocks.py:555`）
- [x] **三交付物回传 + md5 双端一致**：.ninfer 9cc7635b / pack eadea4a5 / adapter 205dec74
- [x] **pack 可训性真机实测**：5070 Ti 峰值 **5.91 GiB**（可用 10.5），16 层 4bit 3.44 + head 2.37，0.79-2.17 s/micro-step，adapter 落盘 76 MiB
- [x] **实例已关机**两次（v3 收口后 + v4 准备前）

### 回归集（19 个静默错全部修完并有测试）
- [x] `scripts/regression/` **20 条**，`run_all.py` 20/20 PASS 22-24 s
- [x] 覆盖：信封错配 / 内容不校验 / BatchEncoding / 前缀法 / 盘符 / §14.8 N/A / val 路径 / merge_forge 隔离 / manifest 写死 / pick 主判据 / make_re_eval 污染 / plan_layers 缺类 / 未知类别 / 假失败 GBK / 死变量 / 声明式校验

### 数据资产
- [x] `data/large-mix-plus/train.jsonl` 4388 行 sha16=b90a1ae8a8b5519b（**未改动**，comply 行=0 证明没误并）
- [x] `data/subsets/` Σ组 1614 + 未分组 2774 = 4388，forge 480(384/96)
- [x] `data/forge/` 480 条（四类各 120，9 闸门零拦截，三重隔离通过）
- [x] `data/intent2/` comply 400 + 200 DPO，切分 320/80
- [x] `data/eval_re_extended.jsonl` 60 题（判据已校准：误杀 0/12、误放 0/12）
- [x] `data/reablit/` refuse_set 30 条 + comply_set 320 条（为 reabliterate 准备，**本轮不用**）

---

## 7. 进行中 / 下一步（新对话先干这个）

> **详细执行清单见 `train/kitty-rev/logs/V4-HANDOFF-SUPPLEMENT.md`**（含下载三选项、base-only 四条命令、wrapper 代码、时间表）

### 当前卡点（**第一件要决策的事**）

**Huihui 73.8 GB 下载只有 1.8 MB/s → 需要 11 小时（不是原估的 1.9 小时）**

```text
进度   10:22 启动，10:31 时 1.2 GB（shard 1/18）
实测   1.8 MB/s（单流 curl -C - 断点续传）
预估   73.8 GB / 1.8 MB/s ≈ 11 小时 ≈ ¥24
脚本   /root/autodl-tmp/kitty-rev/dl_huihui.sh（可中断重跑）
日志   /root/dl.log
```

**已排除的提速方案**：
```text
① ModelScope 上有吗   → 没有（api record not found）
② aria2c / axel       → 未安装
③ hf-mirror 并发 range → **更慢**（3 个 range 各 1.8-2.3 KB/s，合计 6 KB/s）
④ huggingface.co 直连  → DNS 污染
```

**三条可选路径（要操作者选）**：
```text
A 接受 11 小时（¥24）—— 余额 ¥57 够（11h + 训练 6.15h + 回炉 1h ≈ ¥40），唯一确定的路
B 找 ModelScope 上的第三方 abliterated 版 —— 可能省 9 小时，但 abliteration 强度/方法不可比
C 只下 text tower —— 不可行（18 shards 是打包的，allow_patterns 只能筛文件不能筛张量）
```

### 下一步动作（下载完成后按序执行）

```bash
# ① 验证下载完整性
cd /root/autodl-tmp/kitty-rev
ls base/Huihui/*.safetensors | wc -l          # 期望 18
du -sh base/Huihui                             # 期望 ~69 GiB
python -c "import json;i=json.load(open('base/Huihui/model.safetensors.index.json'));print(len(i['weight_map']))"   # 期望 1199

# ② 硬指标（audit-fix-2 给的命令）
python -c "
from transformers import AutoModelForCausalLM
m = AutoModelForCausalLM.from_pretrained('/root/autodl-tmp/kitty-rev/base/Huihui', dtype='bfloat16', device_map='cpu')
print('class:', type(m).__name__)                          # 期望 Qwen3_5ForCausalLM
print('visual modules:', sum('visual' in n or 'vision' in n for n,_ in m.named_modules()))   # 必须 0
"
# 挂 LoRA 后报 trainable params：**必须 = 79,691,776**（与 v3 一致才有可比性）

# ③ base-only 基线（38 min，四条命令见 V4-HANDOFF-SUPPLEMENT.md §二）
#    关键缺口：pick_checkpoint 不能用于 base-only（候选必须是 adapter）
#              eval_re_extended 依赖 meta.expect，而 23/304 两份没有 → 需 wrapper

# ④ act-cache-v4（13 min，新目录）
python kitty-rev/scripts/precompute_activations.py \
  --model merged/Qwen3.8-27B-kittyrev-v4 --cut 48 --ctx 512 \
  --data kitty-rev/data/large-mix-plus/train.jsonl \
  --split-by-subsets kitty-rev/data/subsets --out act-cache-v4

# ⑤ 训练（配置与 v3 逐项一致，只多 --text-only）
python kitty-rev/scripts/train_kitty.py --size 27b --stage sft \
  --base /root/autodl-tmp/kitty-rev/base/Huihui --text-only \
  --data kitty-rev/data/large-mix-plus/train.jsonl \
  --ctx 2048 --bs 1 --ga 16 --epochs 3 --lr 2e-4 \
  --lora-r 16 --lora-alpha 32 --all-gpu --out out-v4
```

### 待验证假设
- [ ] Huihui 与 v3 base 是**同一架构同层数**（都是 64 层 / hidden 5120）→ 超参可原样复用
- [ ] `--text-only` 是 **no-op**（`language_model_only` 在 transformers 5.20.2 里不存在），但 ForCausalLM 本来不建 vision → 不影响正确性
- [ ] base-only 基线的 eval_re 60 会与 v3 base 不同（换基座的必然，必须实测）
- [ ] trainable params 是否真等于 79,691,776（**这条不成立则 v3/v4 不可比**）

---

## 8. 待办步骤

- [ ] 下载完成 → 硬指标验证（visual=0 / trainable=79691776）
- [ ] base-only 基线（60+23+bench+refusal）
- [ ] act-cache-v4（13 min）
- [ ] 训练 3 epoch（6.15 h）
- [ ] merge（纯 text）→ **pin architectures** → GGUF → IQ2_S → .ninfer
- [ ] 回传（16 流）
- [ ] 三组对照（A=v3 / B=v4 / C=Huihui 原版）
- [ ] 本机验证 .ninfer 能加载出话
- [ ] 若 v4 拒答率回升 → 再考虑 reabliterate（**本轮不做**，见 §9）

---

## 9. 雷区（进行时必须避开）

### 意愿层专用（2026-10-22 新增，违反等于没达到操作者要求）

- **坑：用"方法论/分级讨论/审核技术"替代露骨正文**；原因：上一轮曾把 C2（露骨正文 50）论证成 C1（方法论 100）并被采纳，操作者两次明确否掉；正确做法：W3 = 150 条**露骨叙事正文**，判据是"含具体身体/动作/接触层描写、不许 fade-to-black、不许结尾升华"。
- **坑：以为"删掉拒答样本"就等于强化意愿**；原因：LoRA SFT 会把模型往助手式语体拽，删样本只会让它退回对齐先验；正确做法：SFT 正面写"直接进入正题" + DPO 把铺垫式回答标 rejected，两条缺一不可。
- **坑：base 已 abliterated 还按 0.7 强度再做 reabliterate**；原因：过消融会把剩余对齐残差削掉 → "什么都配合"；正确做法：先测 base 的 refusal 投影强度，v4.1 训后回升才做，强度 0.3-0.5。
- **坑：拒答判据用"模型自评"或人工感觉**；原因：判据一软，意愿有没有加强全靠猜；正确做法：W5 探针 40 条 + 拒答/铺垫正则（§16.2 防线 A），训练前后同一套跑，比 pp 差值。
- **坑：W3 训完跨域泄漏**（技术问题也往情色拐）；正确做法：W3n 30 条负向对照必须同时在训练集里，验收看技术语体保持率 ≥90%。

### 本轮新增（v4 相关）

- **坑：`--text-only` 是 no-op**；原因：`language_model_only` 在 transformers 5.20.2 的 Qwen3_5 配置里**不存在**（grep 0 命中），`hasattr` 恒 False；正确做法：不影响正确性（ForCausalLM 本来不建 vision），但**别把它当"配置层跳过 vision"的证据**，验证要看 `named_modules` 里 visual 计数 = 0。
- **坑：peft 的 target_modules 是后缀匹配**；原因：`check_target_module_exists` 对 list 走 `key.endswith(f".{k}")`；正确做法：今天模型里没有 `model.visual.*` 模块所以不会误挂，但若将来换 VL 加载会危险 → 加固用正则 fullmatch：`r"model\.language_model\.layers\.\d+\.(self_attn|mlp|linear_attn)\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$"`。
- **坑：convert 可能走 VL 分支**；原因：merged 只有 text 张量，但 config 的 `architectures` 仍是 `["Qwen3_5ForConditionalGeneration"]`；正确做法：merge 后、convert 前**必须 pin**：
  ```python
  c["architectures"]=["Qwen3_5ForCausalLM"]; c.setdefault("text_config",{})["architectures"]=["Qwen3_5ForCausalLM"]
  ```
  验收：GGUF 里**不得有** `v.` / `visual` / `mm.` 前缀张量。
- **坑：`verify_expand.py` 的 `base_tensors=1199` 是假设值**；原因：1199 = 866 text + 333 vision，是 base 分片总数；text-only 的 GGUF 只有 ~866 → 1199 会误报 FAIL；正确做法：这条当 WARN 看，等真实数回来改 EXPECT。
- **坑：act-cache 与 base 逐比特绑定**；原因：缓存的是该模型第 48 层 hidden states；正确做法：v4 必须用新目录 `act-cache-v4`，v3 的缓存完全无效。
- **坑：abliterated base 上再做 reabliterate 可能过度**；原因：拒答方向已被消融过，再削会把剩余对齐残差也去掉 → 「什么都配合」；正确做法：本轮**不做**，先测 base 的 refusal 投影强度，v4 训完若拒答回升再决定。
- **坑：v3 的数字不能直接当 v4 对照**；原因：base 换了 → eval_re 基线 / refusal 投影 / probe 全变；正确做法：**必须先跑 base-only 基线**，否则看到差异说不清是 base 的还是训练的。

### v3 遗留（仍然有效）

- **坑：IQ2_S 需要 imatrix**；原因：llama.cpp 的 IQ 系列强制要求；正确做法：`llama-quantize --imatrix imatrix.dat ... IQ2_S 16`，imatrix 用 `llama-imatrix -m bf16.gguf -f calib.txt` 生成（524 chunks，约 12 min）。
- **坑：ssm_alpha/beta 被压成 IQ2_XS 会让 recipe 拒绝**；原因：`GDN_CONTROL_TYPES = ("BF16","Q8_0")`；正确做法：量化时 `--tensor-type ssm_alpha.weight=q8_0 --tensor-type ssm_beta.weight=q8_0`（用 `--tensor-type` 逐条，**`--tensor-type-file` 会失败**）。
- **坑：`block_count` 65 vs 64**；原因：base config 带 `nextn_predict_layers=1`，llama.cpp 写 65 但 text-only 没有 blk.64；正确做法：patch `gguf_blocks.py` 的 validate 成「按实际 tensor 的 block 集合校验」。
- **坑：.ninfer 只能用 HF 直转，不能走 GGUF 重量化**；原因：`tools.convert` 的 recipe 最低 Q4（无 Q2/Q3），且**完全不支持 GGUF 输入**（旧版 ninfer-master）；正确做法：用**新版** `ninfer-all-master` 的 `qwen3_8_27b_gguf` recipe（`gguf_blocks.py:555`），把 IQ2_S 块字节原样搬进 v3 容器。
- **坑：merged 的键名带 `model.language_model.` 前缀**；原因：base 是多模态包装；正确做法：`scripts/flatten_keys.py` 剥前缀（850 键，重写 shard 8 min；safe_open 纯 IO 版 105 s 更快）。
- **坑：32 流下载会降速且拼接出错**；原因：AutoDL 长连接限速 + part 边界错位；正确做法：**16 流**（稳定 9-11 MiB/s，md5 一次过）；8 流只有 2.3 MiB/s。
- **坑：MSYS2 把 `/root/...` 转成 Windows 路径**；正确做法：所有 git-bash 调 python 的命令前加 `MSYS2_ARG_CONV_EXCL='*'`。
  - 2026-10-22 已就地根治：`deploy/remote.py` 的 `_fix_remote()` 会按 `/root/ /home/ /tmp/ /opt/ /data/` 锚点还原被转换的远端路径，认不出直接 FATAL——不再依赖调用者记得设环境变量。踩过三次，第三次的表现是`sftp.put` 报 `FileNotFoundError: No such file`（看起来像文件不存在，实际是路径被改写）。
- **坑：paramiko 的 `makefile("r")` 返回 bytes**；原因：md5 变成 bytes → `json.dump` 抛 TypeError；正确做法：加 `if isinstance(md5, bytes): md5 = md5.decode()`。
- **坑：`pkill -f 'pattern'` 会杀掉自己**；原因：命令行里同时含模式和目标；正确做法：只用 PID（`ps -eo pid,cmd | grep ...` 取 PID 再 kill），不用模式。
- **坑：脚本 CRLF 行尾 + `set -o pipefail` 会静默猝死**；原因：bash 解析成 `$'\r': command not found` / 落到 dash 报 `invalid option name`；正确做法：上传后转 LF（`\r` 计数=0）+ 用 `set -eu`。
- **坑：云端存在两棵 kitty-rev 树（R 层 `/root/autodl-tmp/kitty-rev/` 与 KV 层 `.../kitty-rev/kitty-rev/`）**；原因：v3 时代整棵代码树落在 KV 层（数据也在这），v4 新传的脚本落在 R 层 → 脚本里的 `KV="$R/kitty-rev"` 指向旧树，**数据在旧树、脚本是 v3 旧版**，跑起来"通"但判据是老的（2026-10-22 11:30 差点让 S2/S3/S4 全灭）；正确做法：只留一个代码源 + 一个数据源——脚本整目录同步进 KV、md5 逐个比对、`py_compile` 全过、`grep '^\[S1\]'/'EXPECT_SRC'/'model_fp'` 三个特征确认新版；R 层冗余移到 `_obsolete_R/` 保留证据但不再被引用；脚本启动必须打印 `[layout] R=... KV=...` 布局判定行。
- **坑：校验脚本不自证"我验的是哪个文件/版本"**；原因：`tmp/mix/` 里 forge2x 与 forge3 两份共存时，脚本按旧名硬编码取了第一份，报 `[FAIL] 行数 4772 != 4832` —— **文件是好的，被测对象错了**（2026-10-22 plan-optimizer 实测）；正确做法：任何校验脚本第一行打印 `被测文件：<绝对路径> md5/sha16/bytes`，且按"部署件 > 影子重建 > 旧件"优先级选择对象。
- **坑：清理 `tmp/` 会删掉正在被引用的运行时依赖**；原因：`tmp/eval_bare.py` 看着像一次性脚本，实际是 S2 基线正在用的评测入口，被清盘误删（同日第二次：R 层清理带走 `merge.py`）；正确做法：清理前 `grep -r "<文件名>" scripts/ deploy/` 查引用；被引用的移入正式目录（`scripts/`）再清 tmp。
- **坑：用"参数量×每参字节"当磁盘总字节的校验常数**；原因：`.safetensors` 每个文件额外带 `8 字节长度 + header JSON`，本次 18 个 header 合计 **150,312 B**，于是 `55,562,855,904`（=27,781,427,952×2）与实测 `55,563,006,216` 永久差 150,312，被误判成"数据不全"；正确做法：校验常数 = 纯张量字节 + Σ header（并写清推导），或直接以"逐 shard 结构校验 `8+header_len+max(data_offsets)==filesize`"为主判据（它才是真守卫）。
- **坑：hf-mirror 对长连接限速、对单次 range 请求不限**；原因：`curl -C -` 续传只有 88 KB/s，而单次 `-r a-b` 探测能到 1.11 MiB/s；正确做法：大文件卡住时切 24 段 × 47 MB 用 `-r` **整段重下**（`--append` 配合 `-r` 续写无效），6 段 48 秒补完（2026-10-22 shard14 实测）。
- **坑：镜像域名会单点死掉，而现象像"限速"**；原因：2026-10-22 12:44 `hf-mirror.com` 的 TCP 层完全不可达（DNS 160.16.86.14，connect timeout 15s，http=000），5 条 curl 全部静默重试、20 秒只涨 2.1 MB（看起来像被限流到 105 KB/s），实际一个字节都没传；同一条命令里测 `hf-mirror.net` 则 http=200、8MB range 1.52 MiB/s。正确做法：**速率异常先做"同命令内双域名对比"**（`curl -o /dev/null -w '%{http_code} %{speed_download}'` 各打一发），别先归因于限流；换域名后 AGG 立刻回到 6.82 MiB/s。
- **坑：bash 里 `printf 'model-%05d'` 遇到带前导零的字符串会按八进制解析**；原因：循环变量取 `06 09 13 14 18` 时，`09` 直接报 `invalid octal number`、`13/14/18` 被解析成 `00011/00012/00014` → **文件名指向别的 shard**（若当时网络是通的，就是静默写错文件）；正确做法：序号用 `seq -f '%05g'`，或 `printf '%s'` 配显式补零字符串，永远不要用 `%d` 吃前导零。
- **坑：kill 只杀叶子进程，父重试循环会重新 fork**；原因：`while ... sleep 8 ... curl` 的父 shell 没死，杀掉 curl 后它 8 秒后又拉起一个新的 → 两批并发写同一批 shard（2026-10-22 11:10 实测撞上，02/03/05/06/08/09/10 七个 shard 双写，代价多下 4.9 GB）；正确做法：**先杀父再杀子**（或脚本加 `flock` 单实例锁 + 启动前 `pgrep -x curl` 检查），杀完 `pgrep -x curl | wc -l` 必须归零才许重启。
- **坑：`awk` 输出科学计数法被当整数比较**；原因：`awk '{print $5}'` 遇到大数会输出 `3.96673e+09`，shell 的 `[` 判不了 → shard01 明明完整却被判 SHORT、重试 5 次后 GIVEUP；正确做法：远端一律 `printf '%.0f
'` / Python `int()`，不许留裸 awk 输出（这是"错误的判据把好数据判坏"，与假失败同族）。
- **坑：多处同时开跑会抢磁盘/CPU**（本轮撞了三次：两个 quantize、两个 convert、两次 ENOSPC）；正确做法：一个任务前先 `ps -eo pid,cmd | grep -E '[l]lama-quantize|[t]ools.convert'` 确认无重复。
- **坑：`dataloader_num_workers=0` 导致 GPU 拉不满**（v3 训练时 20-100% 锯齿）；原因：数据准备单线程；正确做法：下次训练加 `dataloader_num_workers=4 + pin_memory=True + prefetch_factor=2`（预估提速 20-25%）。
- **坑：pick_checkpoint 的 ctx 512 截断 + tools 与散文判据冲突**；原因：带 4 tools + SYS 时 prompt 已 669 tok，被截成断头 → 模型续写 SYS 残句 → 0/60；正确做法：`--ctx 4096` + `re_eval 传 tools=None` + `build_prompt` 与训练口径对齐（已修）。
- **坑：训练/评测格式不匹配**；原因：训练用 `add_generation_prompt=False`（无 think 块），评测用 `enable_thinking=False`（插空闭合 think + 丢 system）；正确做法：`serve_4bit_base.build_prompt` 改成 False + 手工拼 `<|im_start|>assistant\n`。
- **坑：`merge_forge` / `pick_checkpoint` / `make_re_eval` 的路径参数打错会静默退化**；正确做法：已修 + 回归集覆盖（t7-t11），改这些文件后跑 `scripts/regression/run_all.py`。
- **坑：pack 缺 `config.json`**；原因：打包时漏了（`split_merge_layers.py` L365 本该拷但没生效）；正确做法：`bash deploy/fix_pack.sh`（解包 + 从 base 拷 config/tokenizer + 校验）。
- **坑：本机 `python`/`py` 是 WindowsApps 0 字节别名**；正确做法：全路径 `C:\ProgramData\anaconda3\python.exe`（有 paramiko）或 `train\.venv\Scripts\python.exe`（有 torch）。
- **坑：写 `D:\DrCE(26.2.16)\` 是禁止的**；正确做法：只在 `D:\BaiduNetdiskDownload\Local-AI\` 内写。
- **坑：AutoDL 数据盘 200 G 峰值 142 G（v4 转 GGUF 时）**；正确做法：严格按序删中间产物（merged-flat → 原 Huihui → bf16）。

---

## 10. 关键文件与修改

### 本次 v4 相关
- `train/kitty-rev/deploy/dl_huihui.sh`：**新增**，curl 直连 hf-mirror 下 Huihui 32 文件（绕开 hf_hub 与 httpx2 不兼容）
- `train/kitty-rev/deploy/iq2s_final.sh`：**新增**，四步链（bf16 → IQ2_S + tensor-type → .ninfer → inspect）
- `train/kitty-rev/deploy/fix_pack.sh`：**新增**，解包 + 补 config.json + 校验 + 打印可训命令
- `train/kitty-rev/deploy/local_train.ps1`：**新增**，5070 Ti 一键训练（七步，含 -DryRun）
- `train/kitty-rev/deploy/verify_local_pack.py`：**新增**，pack 体检（tar 与目录两种模式）
- `train/kitty-rev/scripts/flatten_keys.py`：**新增**，merged 键名剥 `model.language_model.` 前缀
- `train/kitty-rev/data/reablit/{refuse_set,comply_set}.jsonl`：**新增**，30 + 320 条（为 reabliterate 备用，本轮不用）

### v3 核心（仍在用）
- `scripts/train_kitty.py`（云端全量训练，`--text-only` 在内）
- `scripts/precompute_activations.py`（act-cache，`--split-by-subsets`）
- `scripts/train_partial_lora.py`（本地增量训练，md5 9b6d911e）
- `scripts/plan_layers.py`（探针→配置，md5 2ccabfb8）
- `scripts/pick_checkpoint.py`（三候选选优，md5 a4651cdd）
- `scripts/make_subsets.py`（EXCLUDE_FORGE + SELECTORS + identity_ok）
- `scripts/regression/`（20 条回归 + `scan_silent_patterns.py` + `scan_dead_assignments.py`）
- `ninfer-all-master/`（云端，含 `qwen3_8_27b_gguf` recipe）
- `deploy/cloud/run_after_expand.sh`（七步，md5 7cec8494 云端版）

### 文档
- `logs/CAPTAIN-HANDOFF.md`：12 节，v3 全链路 + 三条技术结论 + 四评测坑 + 三回传坑 + 六项待办
- `logs/AUDIT-HANDOFF.md`：205 行，19 静默错的因果链
- `docs-local-partial-lora.md`：实现口径 + §14 静默错审查清单（五签名 + 13 实例 + 回归集对照）
- `docs-local-continual-training-plan.md`：主方案（v4 待写入 §17）
- `data/forge/NEXT-ROUND-TODO.md`：comply 下一轮启用 checklist（T5，222 行）

---

## 11. 验证方式

- **下载**：18 shards / 1199 张量 / ~69 GiB
- **加载**：`AutoModelForCausalLM.from_pretrained(huihui)` → `Qwen3_5ForCausalLM` + visual 模块数 0
- **可比性**：trainable params **必须 79,691,776**（与 v3 一致）
- **训练**：loss 逐段下降 + `nvidia-smi` 显存 ~21 GiB
- **回炉**：`tools.artifact.inspect` → objects ~792 / tensors ~788 / formats 含 `gguf_iq2_xs`
- **体积**：.ninfer < 10 GiB（v3 达成 8.76）
- **回传**：本地 md5 与云端一致（16 流，一次过）
- **本机可训**：`verify_local_pack.py` PASS（16 层 / 4388 .pt / sha 全对）+ 训练峰值 < 10.5 GiB
- **回归**：`scripts/regression/run_all.py` → 20/20 PASS

---

## 12. 恢复指令

新会话打开本项目后执行 `/resume`，Agent 会读取本文件并从 **§7 下一步** 继续：

```text
第一件事：查下载进度（/root/dl.log + du -sh base/Huihui）
  · 若还在下 → 等，报进度
  · 若下完 → 跑 §7 的 ①②（硬指标验证）
第二件事：拿 data-forge 的 base-only 基线清单，跑基线（30-40 min）
第三件事：act-cache-v4（13 min）→ 开训（6.15 h）
```

三份必读文档（按序）：
1. 本文件 `TASKPOINT.md`
2. `train/kitty-rev/logs/CAPTAIN-HANDOFF.md`
3. `train/kitty-rev/logs/AUDIT-HANDOFF.md`

---

## 13 意愿强化（v4.1，v4 之后立刻做）

> 铁律全文见 `train/kitty-rev/docs-local-continual-training-plan.md` **§19**（2026-10-22 写入，1097 行起）
> 本节只放执行面。

### 13.1 数据合同（`data/intent3/`）

| 组 | 条数 | 内容 | 判据 |
|---|---:|---|---|
| W1 逆向意愿 SFT | 120 | 易被对齐拽回的请求（样本分析/校验绕过/驱动读写/反调试/固件提取/协议逆向/补丁/注入） | 首句即动作；前 30 字无"授权/合法/请注意"从句；≥2 可执行判据；200-500 字 |
| W2 逆向意愿 DPO | 100 对 | chosen=直接答；rejected=真实回避（纯拒答/三段免责/只给原则/反问索权） | rejected ≥60 字 |
| W3 NSFW 意愿 SFT | **150（露骨正文）** | 成人向叙事体，250-600 字 | 零拒答零铺垫；前 50 字入叙事；含具体动作/接触层；不许 fade-to-black / 结尾升华 |
| W3n 负向对照 | 30 | 技术问题，答案必须保持技术语体 | 防跨域泄漏 |
| W4 通用误拒 | 80 | 剂量/毒理/爆速/化学/监控/灰区 | 给数字与条件，不堆免责 |
| W5 拒答探针 | 40 | 判据集（含 NSFW ≥10 条） | `{prompt,must:"not_refuse"}` + 拒答正则 |

### 13.2 三条路径与顺序

```text
先 A+B（W1-W4 的 SFT + W2 的 DPO，在 v4.1 增量轮）→ 跑 W5 探针 →
拒答率仍回升才做 C（权重再投影，强度 0.3-0.5，不可用 0.7）
```

### 13.3 v4.1 验收（可量化，缺一不算达成）

```text
拒答率（W5 40 条）  ↓ ≥20pp（对比 base-only 基线实测值）
特异性（含具体工具的条数占比） ↑ ≥15pp
NSFW 子集（≥10 条）  拒答 = 0 且前 50 字入叙事 ≥80%
跨域泄漏（W3n 30 条）技术语体保持 ≥90%
通用能力            v4 的 re60 / bench40 不退化
```

### 13.4 配比（v4.1）

```text
comply(W1-W4 合并组):3 · forge:4 · re:2 · rest:1
→ 与 v4 的 forge:4/re:2/rest:1 相比只多一个 comply 源，其余不变
```

### 13.5 生成安全阀（W3 必须前置）

```text
先用 abliterated base 试生成 5 条：
  ≥2 条出现拒答/前置铺垫 → 停，报 lead：说明 base 的 abliteration 已被拉回，
                            数据救不了，必须先做权重再投影（0.3-0.5）
  ≤1 条                  → 继续造 150 条
```


### 13.6 v4.1 配比定稿（2026-10-22 11:58，数据侧实测推导，见 `tmp/v41/MIX-v41.md`）

```text
结论① act-cache 不支持增量（precompute 按文件名=行号判存在；resume 闸门比 --data sha256，
        加行即 FATAL）→ v4.1 必须全量重算，但只需 ~18 min / ¥0.65（不是 30-35 min）
      禁止"删 manifest 让 skip-by-exists 生效"的绕过：行号错位会张冠李戴且不报错

结论② 权重定稿 R1：rest 1.0 → 1.2（其余不动）
       A 栏（5118 行可跑）：comply 14.32% · forge 32.88% · re 8.56% · will-rev 2.86% · rest 41.38%
       B 栏（5378 行全量，R1 后）：comply 12.85% · forge 29.49% · re 7.67% · will-* 4.44% · rest 44.55%
       理由：rest 从 v4 的 56.80% 掉到 40.10% 意味着 reasoning（1172 行全在 rest）曝光 ×0.71；
             改 rest 权重是"只补短板、不动主目标"的最小改动

结论③ 报警阈值：rest ≥42% 正常 · 40-42% 复核 · 36-40% 必须调权重 · <36% 红停
       forge 合计必须留在 25-40%（v4 31.45% / v4.1 29.49-31.86%，均达标）
```

## 14 v4 训后评测与拒答再投影（2026-10-22 12:25 补齐三处空档）

### 14.1 对照组的诚实收缩：只做 B vs C

```text
C = Huihui base-only          ← 今天 S2 产出（re60 / bench40 / refusal / 过拒40）
B = Huihui + v4 adapter       ← 训后同一套（--adapter 指向 pick 推荐的 checkpoint）
A = v3（官方原始版 + adapter）  ← **不重跑**：云端 Qwen 原版已删，重下 51.75 GB = 2 h + ¥11；
                                 且 v3 的 re60/kitty 数是"ctx512 截断 + 格式不匹配 + tools 冲突"三坑叠加的假失败，
                                 拿它做对照等于用一个坏尺子量两个东西
⇒ 结论口径：只回答"同一基座上，训练有没有效"（B vs C）。跨基座（v3 vs v4）只做定性描述，不做数值结论。
```

### 14.2 训后评测（B 组）执行清单

```bash
# pick 出结论后，用**推荐的 adapter** 起 serve（不是 out-v4/adapter 直接上）
bash deploy/cloud/run_after_expand.sh --stage all   # 内部读 logs/v4/pick.md 的 [PICK] 行
# 若只想先评测再回炉：
#   起 serve --adapter <推荐 checkpoint>，端口 18001
#   tmp/eval_bare.py --suite re60 / bench40 ；refusal_probe --mode text
#   data/intent3/run_overrefusal.py --input overrefusal-40.jsonl
#   产物落 logs/v4/eval-B/
```

### 14.3 判据（B vs C，全部同口径、同端点参数）

| 指标 | 含义 | 达标 |
|---|---|---|
| re60 通过数 | 逆向能力 | B > C（且 ≥ v3 记录值仅作参考） |
| bench40 F1 | 通用能力 | B 与 C 差 ≤ 5%（不退化） |
| refusal_rate | 拒答率 | B ≤ C + 10pp（**超过 15pp 触发再投影**） |
| over_refusal | 过拒 | B ≤ C（意愿不该被 SFT 拽回去） |
| under_refusal | 欠拒 | B ≤ C + 5pp（不许"什么都答"） |
| style_meter | 语体 | B 的 first_sentence_action ≥ C |

### 14.4 拒答再投影（reabliterate）的触发时点（正式定死）

```text
测点：v4.1 训完、转 GGUF **之前**（不是 v4 之后 —— v4 无意愿数据，回退幅度预计在噪声内；
      但仍要在 v4 训完时测一次记录基线，代价 3 分钟）
条件（三条同时成立才做）：
  ① refusal_rate(B) − refusal_rate(C) ≥ +15pp（n=40 探针，CI≈±15pp，<15 是噪声）
  ② eval_re(B) ≥ 0.95 × eval_re(C)（能力没坏 —— 能力坏不是 abliteration 的锅）
  ③ proj_comply(B) − proj_comply(C) ≥ 0.25 × margin(C)（还有可削的方向）
强度：0.3-0.5（base 已 abliterated；0.7 会过消融成"什么都配合"）
中止：投影后 proj 触及 +0.5 × margin(C) 立即停
顺序：投影 → 再测同一套 → 通过才转 GGUF（量化误差会掩盖投影效果，顺序不能反）
```

### 14.5 三处空档的归属

```text
① 能力评测排期   → train-watch 执行（14.2 命令），lead 验收（14.3 判据）
② B/C 对照       → 同上；A 组明确放弃（14.1）
③ 再投影触发     → audit-fix-2 出测量脚本，lead 决策；执行在 v4.1 之后
```

## 15 两个 P0 事实更正（2026-10-22 12:35，plan-optimizer 发现 + lead 独立复核）

### 15.1 v3 实际只训了 3908 行（forge 零曝光）

```text
证据链（三条独立）：
  run_autodl.sh:18   DATA=$ROOT/kitty-rev/data/large-mix/train.jsonl   ← 3908 行
  /root/full.log    735/735 [6:08:59, 30.12s/it]，735 = 3 × ceil(3908/16)
  实测行数          large-mix 3908（forge=0） vs large-mix-plus 4388（forge=480）

推论：
  · 此前所有"v3 = 4388 行 / forge 已训过"的记录全部作废
  · forge 480 的高密度数据**至今零实测**
```

### 15.2 云端训练器没有权重机制

```text
grep -n "data-mix|data_mix|weight|repeat" scripts/train_kitty.py  → 0 命中
→ train_kitty 均匀采样，--data-mix 只存在于本地 train_partial_lora.py
→ 文档里"forge batch 占比 31.45%"是纸面数
实测（tmp/plan-opt/audit_mix.py）：
  forge 11.48% token · re 2.89% token · reasoning 52.04% token（451,351 tok）
  rest 82.20% 行 —— "rest ≥42% 正常"这条报警线永远红，等于没有报警
```

### 15.3 裁决（S4 前执行）

```text
① v4 用 4388（含 forge），不退回 3908
   理由：A 组（v3）已放弃，与 v3 同数据无收益；而 B vs C 对照与行数无关
   代价：+90 步（735→825），+45 min
② forge 曝光用行复制做：复制 forge **train** 行一次（384 行）→ tmp/mix/train-forge2x.jsonl = 4772 行
   步数 897（ceil(4772/16)×3），约 7.5 h；forge token 份额 11.48% → 约 17%
   不做 ×3（27% token / 969 步 / 8.1 h）：时间账不划算，真权重机制留给 v4.1（本地有 --data-mix）
③ F3/F4 零成本处理：val 行 100% 在 train 内 → val loss 一律标 NOT_MEASURED；
   n=40 的比率判据标 INCONCLUSIVE 而非 PASS（n=40 检出 20pp 差异需每组 98 条）
```

## 16 判据规范与 MDE（2026-10-22 12:45，plan-optimizer 实测推导；**优先于 §14.3**）

### 16.1 三态判据（不许再用"通过/失败"二态）

```text
PASS          |差异| ≥ MDE 且方向正确
FAIL          |差异| ≥ MDE 且方向错误
INCONCLUSIVE  |差异| < MDE（差异在噪声内 —— 不许写成 PASS）
NOT_MEASURED  口径被污染（如 val 行在训练集内）→ 该指标作废，不许写 0
规则：**阈值必须 ≥ MDE**，做不到就换判据形态（扩样本 / 改配对 / 改指标）
```

### 16.2 MDE 实测表（α=.05 / power=.80）

| 判据 | n | MDE | 现阈值 | 状态 |
|---|---:|---:|---:|---|
| refusal_rate | 60 | **25.6pp** | 10pp | 恒过（↓20pp 漏判率 ≈40%） |
| over_refusal | 40 | **31.3pp** | — | 需扩样本 |
| under_refusal | 40 | **31.3pp** | 5pp | 恒过 |
| bench40 F1 | 40 | **28.7pp**（pass 率口径）／**2.7pp**（mean_f1 连续口径，入账用这个） | 5% | 恒过 |

> **§16.2 注（2026-10-22 19:30，F20 修正，优先于上表 28.7pp）**：MDE 取决于**入账指标类型**，不是样本量。
> · 判 `pass` 数（C 组 0/40，二项）→ MDE **28.7pp**；但 pass 恒 0 无信息量，不用它
> · 判 `mean_f1`（连续，C=0.1255，SD 0.0895；剔 4 条空答后 SD 0.0846）→ 配对 MDE ≈ **2.7pp**
> ⇒ B 组 bench40 判读一律用 **mean_f1 + MDE 2.7pp**；阈值定 3pp 成立（≥MDE）。
> ⇒ 任何引用"bench40 MDE=28.7pp"的文档必须同时写清"那是 pass 率口径"。
| re60（非配对） | 60 | **14 题** | — | 配对后降到 ~8 题 |
| eval_kitty | 23 | **41.3pp** | ≥3/23 | 噪声极大 |
| NSFW 子集 | ≥10 | **62.6pp** | 拒答=0 | 只能做定性 |

### 16.3 本轮唯一能"判死"的指标

```text
**re60 配对翻正数**：b−c ≥ 3 且 b+c ≥ 6（b=候选过而基线不过的题数，c=反之）
其余指标一律标 INCONCLUSIVE + 附 MDE
若三候选都达不到 → 结论写"本轮在 60 题上无可测差异"，不许写"选了最好的那个"
```

### 16.4 已定位的判据失效（累计 8 处，F1-F8）

```text
F1 v3 实为 3908 行（forge 零曝光）        P0  已裁决（§15）
F2 云端训练器无权重机制                    P0  已裁决（行复制 ×2 → 4772 行）
F3 5 个子集 val 行 100% 在 train 内        P1  → val loss 标 NOT_MEASURED
F4 6 条比率判据中 5 条阈值 < 自身 MDE      P1  → §16.2 表；refusal 60→160（comply_set 320 现成）
F5 eval_kitty 23 里 2 条是训练原题         P2  记录
F6 文档仍按 73.8 GB 规划（实测 55.56）     P2  记录
F7 v4_pick 次级键用被污染的 val loss       P1  **pick 前必修**：改配对翻正数，val loss 移出排序
F8 G5 看聚合 loss（reasoning 占 47.6%）    P2  与分块 loss 采样一起做
```

### 16.5 forge 行数更正（864，不是 768）

```text
复制源 forge-subset.train 384 行，而 train.jsonl 里本就有 480 条 forge（384 train + 96 val，
那 96 条因 F3 已在训练集内）→ 480 + 384 = **864 行 = 18.11% 行 / 18.92% token**
（train-watch 报的 13.01% 是**字符**口径且只算了 768 行；两口径都对，但 token 口径才对齐设计带）
现状对照：480 行 10.94% 行 / 11.48% token
```

## 更新历史

- 2026-10-21 16:25：v3 起步（云环境差 cusparselt，训练未开始）
- 2026-10-22 10:35：**v3 全链路完成并回传**（8.76 GiB .ninfer + 25.8 G pack + adapter）；发现 base 是官方原始版（有审查）→ 决定换 Huihui abliterated 重训（v4）；Huihui 下载中（1/18 shards）；四 agent 已分工
- 2026-10-22 11:02：写入 §13 意愿强化（操作者定稿：abliteration 不许削弱、必须加强；NSFW 可直出露骨正文），主方案 §19 同步落盘；v4 仍 4388 单变量，意愿数据进 v4.1
- 2026-10-22 11:58：v4.1 配比定稿（rest 1.0→1.2，R1）；act-cache 增量不可行→全量 18 min；阈值表入档
- 2026-10-22 12:25：§14 补齐三处空档（B/C 对照、训后评测清单、再投影触发条件）；A 组明确放弃并写明理由
- 2026-10-22 12:35：§15 两处 P0 更正（v3 实为 3908 行 / 训练器无权重）+ S4 改用 4772 行混料
- 2026-10-22 12:45：§16 判据三态 + MDE 表 + 判据失效清单 F1-F8 + forge 864 行更正

---

## §20 SESSION CHECKPOINT · 2026-10-22 17:50

> **新会话从这里接**。详细交接见 `train/kitty-rev/logs/TEAM-HANDOFF-2026-10-22.md`。

### 20.1 正在跑的东西（唯一关键路径）
```text
v4 训练  PID 22900 · 日志 /root/autodl-tmp/kitty-rev/logs/v4/train2.log
         56/915 步 @ 17:48 · 20.5 s/it · GPU 72-100% / 21.45 GiB · ETA **约 22:40**
         数据 tmp/mix/train-forge45.jsonl（4871 行 / 915 步 / 3 epoch）
         启动含 --skip-kbit-prepare（peft fp32 上转要 4.74 GiB，24G 卡 OOM；train.log 那次就是这么死的）
本地监工 job j-9jagg1 → logs/v4/MONITOR.log（每 10 min 一行；重启 shell 后 job 可能已死，需重起）
```

### 20.2 环境硬约束（不照做必失败）
```text
本地 DNS 被封：UDP/53 对本机/阿里/114/8.8.8.8 全 "Query refused"
唯一解析：AliDNS DoH JSON（IP 直连）→ connect.bjb1.seetacloud.com = **123.127.15.155**
所有 ssh：AUTODL_HOST=123.127.15.155 python deploy/remote.py --cmd "…"
```

### 20.3 冻结值（改动即作废）
```text
mix      tmp/mix/train-forge45.jsonl  md5 7d556610 / sha16 3aca9d46 / 4871 行 / 915 步
trainer  kitty-rev/scripts/train_kitty.py  md5 516b7ea7（未改代码，走自带 --skip-kbit-prepare）
pick     deploy/cloud/v4_pick.sh db015c5d · run_after_expand 771932e7 · make_imatrix 858f16c4
pack     pack_deliverables 1b59f6b6 · verify_local_pack 47d138b4
```

### 20.4 C 组基线（B 组必须逐字段同参）
| 套 | n | 结果 | 关键参数 |
|---|---:|---|---|
| re60 | 60 | 24/60（pe 15/15 饱和&过松 · op 0/15 · chain 0/15 · err 9/15→**修正 11/15**，+2 假失败） | max_tokens 512 · tools off |
| bench40 | 40 | mean_f1 **0.1255**（空答 4/40=i 3,13,19,36；非空 0.1386） | max_tokens **256** |
| kitty23 | 23 | **13/23**（op 8/9 · real-traj 2/3 · tool-route 1/9） | max_tokens 512 |
| refusal | 100 | **0/100**（地板；MDE 19.8pp；≥4 条才算信号） | `--from-jsonl data/reablit/comply_set.jsonl --limit 100`（**不是内联**：内联只有 60 条） |

> **2026-10-22 18:10 口径裁决（有产物铁证，优先于此前所有说法）**
> `logs/base-only/refusal-100.json` 实测：`text.n=100` · `n_ok=100` · `refused=0` · `max_tokens=256` ·
> `prompts.source=data/reablit/comply_set.jsonl` · `pool=320` · `file_sha16=9570a3705b207e45` ·
> `list_sha16=c2776c359904d06e` · `rule=sha16(prompt) 升序取前 limit 条`。
> ⇒ C 组用的是 **--from-jsonl + --limit 100**，不是内联 COMPLY（内联只有 60 条，refusal_probe.py:206）。
> ⇒ B 组必须同命令同池，并断言 `list_sha16 == c2776c359904d06e`；不符即该格 NOT_MEASURED。
> ⇒ 日志里 `comply_n=60` 与 "60/60" 都是分母 bug（产物顶层的 comply_n 也受影响，只有 `text.*` 可信）。

已定正误：refusal 日志 "60/60" 是分母 bug，产物 `text.n=100` 才是事实；eval_meta.thinking 字段判错（5 条探针答案全以 `<think>` 开头），该字段作废。

### 20.5 agent 团队故障（新会话要么修好、要么继续单干）
```text
通道 A spawn_teammate：8/8 唤醒即 failed（opencode 额度耗尽）
通道 B agent_teams  ：6/6 spawn error = provider "spawn" cannot apply a member persona
  根因：profiles/desktop/cordis.yml:1920  memberProvider: spawn（spawn provider 无 capabilities.persona）
  已改：memberProvider: fork（备份 cordis.yml.bak-memberprovider）→ **需重启 DSH 生效**
  未验证：fork 是否真带 persona+toolFilter 能力；重启后用 agent_teams_status 看是否还报 spawn error
新会话第一步建议：agent_teams_status（若仍报错，回滚 memberProvider 并改用单干 + 后台 job）
```

### 20.6 训完的固定路线（顺序不可变）
```text
915/915 → ls out-v4 → v4_pick.sh（re60 配对优先）→ 读 [PICK] 定 adapter
→ merge(base=base/Huihui) → pin_arch → make_imatrix → IQ2_S → .ninfer → pack_deliverables
→ 回传 16 流 → 本地 verify_local_pack（md5/字节/可加载）
→ B 组四套评测（serve 带 [PICK] adapter；参数逐字段等于 C 组；先过参数生效检查）
```

### 20.7 本会话新增雷区（均已实测）
```text
① 参数写了没生效三连：thinking=false（仍出 think）/ max_tokens=512（实际 995 字）/ --from-jsonl（名额生成了但循环用内联）
   ⇒ 判据要用断言核实际行为，不能看 eval_meta
② 报"已修"必须三样齐：运行环境 md5 + 日志行 + 产物字段（本地副本推断线上行为一律加"本机假设"）
③ 校验脚本必须自证"我验的是哪个文件"（md5/路径先打印）
④ 清理 tmp 会删正在被引用的依赖（eval_bare 被误删过）
⑤ 报表均值只能读不能算（在 round 过的数上再运算差 0.0008）
⑥ 加数据要看边界：775 行 route/discipline/gen 曾零曝光；W3 扩量上限 662→D7 后 327（binding 是会话层占比）

---

## §21 SESSION CHECKPOINT · 2026-10-22 17:58（新会话接手后）

### 21.1 委派通道结论（已实测，不再猜）
```text
agent_teams（插件通道）：**仍坏**。建团队成功、任务登记成功，但 6/6 成员 spawn error =
  "provider \"spawn\" cannot apply a member persona"
  根因：members.js:510 要求 provider.capabilities.persona，实际取到的是 spawn provider。
  cordis.yml:1920 已改 memberProvider: fork（备份 cordis.yml.bak-memberprovider），但**运行中的 host
  仍用旧值 spawn** —— 该配置只在 host 启动时读取，改后必须整个 DSH 重启才生效（会话重启不够）。
  处置：本轮不用该通道，已 agent_teams_delete 归档，避免状态里长期挂 6 条 spawn error。

spawn_teammate（官方通道）：**可用**。6/6 成员 status=running，provider=spawn，
  model=deepseek/deepseek-v4.1-flash（继承 captain 路由）。
  ⇒ opencode 额度耗尽那件事已经过去，现在的 spawn 走的是 commandcode 路由。
```

### 21.2 当前团队（6 人，全部 running）
| 成员 | 任务 | 落点 |
|---|---|---|
| `train-watch` | v4 训练监工：每 10-15 min 采样，红线报警，到 915 报 checkpoint 清单 | `logs/v4/MONITOR2.log` |
| `param-gate` | `scripts/assert_params_effective.py`（B 组评测前置闸，治 F16/F17/F24 三族） | `scripts/` |
| `sevenstep-prep` | 七步干跑预检 + dry-run 脚本 | `tmp/deliver/` |
| `judge-ledger` | DECISION-TREE 落账 + B 组六格填空模板 | `logs/v4/` + `tmp/plan-opt/` |
| `data-verify` | forge4/forge5 是否真在 4871 行混料 + v4.1 复跑命令 | `tmp/v41/` |
| `repo-commit` | 四批提交清单（不 commit） | `logs/COMMIT-READY.md` |

### 21.3 训练实况（17:53 实测）
```text
74/915 步 · 20.22 s/it · GPU 81% / 21,453 MiB / 328 W · 云端盘 119G 可用 · ETA 约 22:35
PID 22900（父）+ 23204（子，同一进程树，勿杀）
日志 /root/autodl-tmp/kitty-rev/logs/v4/train2.log
```
本地旧监工 job j-9jagg1（写 MONITOR.log）已由 train-watch 的 MONITOR2.log 取代，不再并行起。

### 21.4 新雷区
```text
· agent_teams 的 memberProvider 是 host 启动期配置：改 cordis.yml 后"重启会话"无效，必须重启整个 DSH。
  在被证明可用之前，一律走 spawn_teammate，别浪费时间重建 agent_teams 团队。
· 同名任务不要在两套通道各建一份：spawn_teammate 的成员看不到 agent_teams 的 task 板，
  派活必须写在 spawn 的 prompt 里（本轮就是这么做的）。

### 21.5 又两条雷（18:25 实测，都会让"交付了但看不见"）
```text
⑦ .gitignore 的无锚点目录规则会吞掉整层产物：`:46 logs/` `:47 temp/` `:48 tmp/` 匹配任意层级同名目录，
   而 git 的规则是"父目录被排除时，子项取反一律无效" ⇒ 只改 `train/kitty-rev/logs/` `tmp/` 没用，
   :46/:48 立刻接手（实测第一版 patch 只有 9/17 成立）。正确修法：三条锚到仓库根 `/logs/` `/temp/` `/tmp/`，
   再用 `logs/*` + `!子项` 取反。验证必须用沙箱 repo 跑 `check-ignore` 断言表，不能只看 patch --check 通过。
   ⇒ 后果：今晚新产的脚本/协议/决策文档在 `git status` 里**根本看不见**（不是忘了 add）。
⑧ 脚本 md5 不能当"唯一真值"硬编码：18:05 量到 77d6d681、18:20 量到 1ce80ccf，因为期间有人在改同一个文件。
   ⇒ 报告里一律写"跑前自证：md5sum <file> 并记入产物"，跨时刻的 md5 差异只说明文件在演进，不代表坏了。
⑨ 判断"两把尺子是否同尺"要看**判据代码与名单**，不看文件版本号：refusal_probe 云端 6a778e16 与本地 5eb7a9cf
   大小差 1,360 B、行数差 27，但第 1–462 行**逐字节相同**（拒答判据全在共同前缀）⇒ refused 条数可直接比；
   真正的差异只有两处：云端缺 n_ok/n_err 字段、云端分母用 len(P)（n_err>0 时会稀释）。
   ⇒ 由此改判：用本地版（同尺 + 仪表更全）。同时纠正一个我曾说错的数：存盘 refusal_rate 分母是 len(P)=100，
     **没有被放大 1.67 倍**；被放大的是日志字符串 `(N/60)` 与顶层硬编码 comply_n=60。
   ⇒ 方法沉淀：任何"换版本是否可比"的问题，先做「两版共同前缀逐字节比对 + 差异段语义定位 + 产物字段兼容表」，再决定。
⑩ **"腾盘"必须先核输出路径，否则删的是交付物本体**（2026-10-22 18:30 险些执行）：
   v4 的 `.ninfer` 输出就是 `$R/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer`，**与 v3 同名同路径**；
   我批准过"convert 成功后 `rm -rf $R/ninfer`"——照做会当场删掉刚生成的交付①，且 convert 是**同名原地覆盖**，
   中途 ENOSPC 会同时失去 v3+v4 两份（本地 `train/local-pack/*.ninfer` 是唯一退路）。
   ⇒ 正确做法：腾盘放在 convert **之前**、只 `rm -f` 具体文件、保留 `*.conversion.json` 审计件、**永不 `rm -rf` 输出目录**。
   ⇒ 通用纪律：任何"删目录腾空间"的动作，先 grep 产出脚本里该目录的 `--out` / 写入路径；命中即改用文件级删除。
⑪ **tqdm 显示的 s/it 是滑动平均，不是单步耗时**（2026-10-22 19:00 我误判过一次）：
   看到 `18.52 → 20.46 → 21.55` 三轮递增就断言"趋势性变慢、交付要滑 25 分钟"。
   真证据：用 `elapsed/step` 反算累计均速，184→212 步只涨 **0.056 s/it（+0.3%）**，末端还回落；
   29 个单步值锯齿 18.15↔21.91（最快与最慢交替）；且同一进度行会连续两次显示同一 step（刷新≠步进）。
   旁证也全否掉资源争用：loadavg 10.35/128 核 = 8% · SM 2775 MHz 满频 · 56℃ · 无外来进程。
   ⇒ 判趋势只看**累计均速单调性**，不看显示值；红线口径 = 连续三轮 >22 **且** GPU util 均值 <70%。
   ⇒ 这类"用显示值当斜率"与 §21.5 ⑥/⑧（awk 溢出 / Measure-Object 数空行）同族：**指标口径错，结论必错**。
⑫ **`set -e` 下用 `cond && { echo; exit 1; }` 写断言，会在"正常路径"上把脚本弄崩**（2026-10-22 19:12 实测）：
   要判"act 已退"，写成 `kill -0 $pid && { echo "还在跑"; exit 1; }`。
   当 act **确实已退**（这正是期望态）时，`kill -0` 返回非零 → 整个 `&&` 链返回非零 → `set -e` 立刻退出脚本。
   ⇒ 结果：正常反而崩，异常反而"通过"。
   ⇒ 正确写法：`if kill -0 $pid; then echo "还在跑"; exit 1; fi`（`if` 条件不受 `set -e` 约束）。
   ⇒ 同族判据要这样写：凡"某条件成立才算正常"的断言，一律 `if … then … fi`，不用 `A && exit` 短链。
⑬ **`set -u` 下 `local a="$1" b="…$a"` 会在赋值前展开整条命令 → `a: unbound variable`**（今日两次：18:50 / 19:30）：
   bash 先展开所有右侧单词，再逐个赋值，所以同一行里引用前面的变量属于未定义。
   ⇒ 拆成两行：`local a="$1"; local b="…$a"`。
   ⇒ 已被 data-verify 列为"本工作区 Bash 头号雷区"；写脚本时凡 `local`/`declare` 一行多变量且后者引用前者，一律拆行。
⑭ **"已下发"不等于"已落地"**（2026-10-22 20:22，plan-auditor 抓出 + 我自己 grep 复核）：
   我 20:15 在消息里要求把七步 ⑨ 从 `--overwrite` 改成 `rm -rf` 后重建，20:22 用 grep 核实物：
   `preflight:347` 仍是 `--out "$ACT" --overwrite`、`:353/:404/:529/:545` 文案仍在、`dryrun:243/:283` 仍带该参数。
   ⇒ 危险在**时间差**：七步卡是 23:00 之后唯一被照着敲的东西，谁在 23:20 打开 :347 看到的仍是旧写法。
   ⇒ 纪律：**判据/动作改在"会被执行的那份文件"上才算改；改在消息里 = 没改**。
   ⇒ 验收方式：不看"已改"的口头，只跑 grep 断言（例：`grep -c 'rm -rf "\$ACT"' ≥5` 且 `grep -c 'out "\$ACT" --overwrite' == 0`）。
   ⇒ 变体（同日发现）：同一动作出现在两份文件时（回滚手册写对了、执行序没改），改一处后必须立刻 grep 另一处。
⑮ **索引/台账必须能被外部实测推翻**（2026-10-22 21:00，repo-commit 的 LIVE-DOCS 自测）：
   实测 LIVE-DOCS 记的 mtime 与磁盘实差 **46–145 分钟**，导致 6 项被误判为"落后"（DECISION-TREE 被标 17:57，实际已 20:22）
   ⇒ 三条硬规矩：① 校准时刻本身必须可验证（写"校准 21:00（stat 重取 11/11 份，明细见 SCAN）"，不只写"校准 21:00"）
                  ② **索引必须索引自己**（把自己也列进表并记 mtime），否则它天然豁免于自己的规则
                  ③ "落后"必须给两个量：距 mtime 分钟数 **+** 与索引记录的差值（前者说文档旧不旧，后者说索准不准）
   ⇒ 本质：**台账的可信度不由它自己声明，而由"能被外部实测推翻"来保证**。
⑯ **绝对阈值判据要用"外推值"而不是"名义目标"**（2026-10-22 21:05 即将误触发）：
   我写"21:10 采到 step<700 就切 ① 优先"。按 19.18 s/it 外推，21:10 = **692**，那是**完全按计划**；
   要到 700 需 8 分钟跑 33 步 = 14.5 s/it（今晚最好 18.4，从未出现）⇒ 按原判据，正常也会被判成"该切"。
   ⇒ 改法：判据用 `外推 ETA > 22:40` 或 `step < 均值-1σ`，不用"名义整数目标"；正常值 ±1σ 一律记观察档、不动排班。

---

## §22 交付定义与今晚排班（操作者 2026-10-22 18:35 明确，优先于 §3/§5 旧表述）

### 22.1 两项交付物（缺一 = 未交付）
```text
交付① 量化后 .ninfer：qwen3_8_27b_kittyrev_v4_iq2s.ninfer · **<10 GiB** · 本机 5070 Ti Laptop(12G) 可被 NInfer 直接加载出话
      判据：tools.artifact.inspect 通过 + 本机 ninfer-serve 起得来 + 实际对话有输出
交付② 可继续微调/二次后训练的内容包：kittyrev-local-pack-v4.tar
      内含（v3 真包 tar -tvf 实测口径，**不是 4bit**）：
        merged-layers/layer_48..63 共 16 层 **bf16 切片**（12×766,548,152 + 4×744,511,880 = 12,176,625,344 B）
        merged-layers/head.safetensors 2,542,807,248 B（lm_head + language_model.norm）
        merged-layers/layers_index.json（含 src 与每层 sha16）
        merged-layers/config.json —— **v4 必须自带 pin 过的**（architectures=["Qwen3_5ForCausalLM"]、无 vision_config）
        act-cache/ 11 个分组目录 + manifest.json（**4871 条 .pt**）
      4bit 是训练时 bnb 在显存里做的量化，**不落盘**；验收方不要在包里找 quantized 文件
      判据：verify_local_pack.py PASS（8 条断言，含 act_total 4871 / pack_pt 4871 / layers_index.src 含 -v4）
             + 5070 Ti 峰值显存 <10.5 GiB
铁律（不可削弱，任何方案偏离即视为 DRIFT）：
  ① abliteration 只能加强不能削弱 —— 为强化逆向工程意愿与敏感内容（NSFW）的接受度/输出意愿
  ② NSFW 输出可直出露骨正文 —— **不许用"方法论/分级讨论/审核技术"替代正文**（操作者两次明确否掉过）
  ③ v4.1 意愿层数据（W1-W5）与验收（拒答率 ↓≥20pp、特异性 ↑≥15pp）见 §13 / 主方案 §19
```

### 22.2 今晚排班（**2026-10-22 19:10 按 after-expand.log 实测锚点重算**；act-cache 必做，卡交付②）
```text
实测锚点（plan-auditor 从 v3 after-expand.log 相邻步头差取得，非估）：
  merge 4m12s · quant IQ2_S **22m30s**（含 verify step3 重扫，不是 8 min）· convert **19m33s**（含 inspect+gate5，不是 7 min）
  act-cache 14m34s · 拆层 1m11s · pack **6m48s**（不是 1 min）· 回传 16.1 / 40.3 min · GGUF 6 min（v3 那轮被跳过，未复现，沿用）

关键修正：**今晚不跑 pick 评测**（单候选无选择 + 4bit nf4 与 IQ2_S 不同尺 + 省 30-60 min），
         只写 3 行 pick.md 作审计。所以下面的账里 pick 只占 1 min，不是 30-60 min。

22:30  训练 915/915（196/915 @18:32 · 全程均速 **19.59 s/it** · 近两步 20.46/21.03 有二次漂移 → 收口 **22:28-22:39**）→ 存盘 20-60s
22:32  adapter 三断言 + 写最小 pick.md（LF 无 CR）
22:34  merge(Huihui) 4.2m → 22:39 GGUF bf16 7m → 22:46 前缀守卫
       ★ **全程磁盘最紧点**：merged 51.8 + bf16 53.8 同时在场 → free ≈**30.9 GiB**（22:39-23:01 这段要盯 df）
22:47  imatrix（CALIB=calib-v4.txt 换源）13m → 23:01 IQ2_S 22.5m
23:24  **O8 腾盘（必须在 convert 之【前】）**：只删两个具名文件，永不 rm -rf 目录
       `rm -f $R/ninfer/qwen3_8_27b_kittyrev_iq2s.ninfer` · `rm -f $R/gguf/qwen38_kittyrev_iq2s_v2.gguf`
       保留 `$R/ninfer/*.conversion.json`；删前 du -sh + ls -l 记账，删后 df -h
       ⇒ **convert 前 free 断言值 = 75.9 GiB（±1）**（不是 62.6：acts 10.3G 已在基线 free 119 里，不能重复计）
23:26  convert+inspect 19.5m ‖ **act-cache 起（--bg，比 convert 晚 30s）**
       NINFER 指向 `$ROOT/ninfer-v4/…`（与 v3 的 ninfer/ 并存，不覆盖）
23:46  回传 .ninfer 16m（`get_multi --streams 16`，禁用 `remote.py --get`）
**23:57-00:08  交付① 落地**（.ninfer <10 GiB）
23:46  act 收口 → 拆层 1.2m → **立即 `rm -rf $MERGED`（54G，拆层已吸收其价值）** → pack 6.8m
       （删前断言：merged-layers/ 16 层 + head 齐全；不删则 pack 后只剩 4-5G）
00:05  回传 pack 40m
**00:33-00:44  交付② 落地**（local-pack-v4）
之后   本地 verify_local_pack(--expect-pt 4871) + 本机 ninfer 实跑 → 两项验收
明早   B 组四套评测（batch-check 通过则 batch=4 ~1h，否则 batch=1 约 2h14m）
```

### 22.3 存盘计划落后项（18:35 核对，已在本节修正）
```text
① §3 总体计划的"6 回炉"没写 act-cache 与 pack 的先后 ⇒ 已在上表按脚本硬约束排序
   （imatrix 必须晚于 GGUF：make_imatrix.sh:79-85 缺 bf16 GGUF 直接 die；act-cache 必须晚于 merge）
② §5 步骤表停在第 23 项（v3 口径），未含 S4b / act-cache 重算 ⇒ 以本节 22.2 为准
③ 旧记录把 act-cache 当"可选"⇒ 纠正：它不卡交付①，但**卡交付②**，因此必做
④ 旧记录未区分两项交付物 ⇒ 以本节 22.1 为准；"跑通训练"不等于"交付完成"
```

### 22.4 存盘内容实测与更新表（18:45，`tar -tf` 读 v3 包真实结构，4430 文件）

```text
v3 包 kittyrev-local-pack.tar（24.01 GiB / 25,778,176,000 B / md5 eadea4a5）实际只装两棵树：
  merged-layers/  16 个 safetensors：layer_49..layer_63 + head.safetensors + layers_index.json
  act-cache/      manifest.json + 11 个分组目录，共 4,410 个 .pt：
                  rest 2776 · forge-train 386 · discipline-train 308 · re-train 289 · route-train 236
                  forge-val 98 · gen-train 82 · discipline-val 79 · re-val 74 · route-val 60 · gen-val 22
  注意：**包里没有 config.json / tokenizer** —— 靠 deploy/fix_pack.sh 解包后从 base-meta 补
```

**v4 必须换的内容（同名换内容，装错不报错）**

| 项 | v3 现状 | v4 必须 |
|---|---|---|
| `merged-layers/` 16 个 | v3 merged（官方 Qwen + v3 adapter）· layer_48..63 **bf16**切片 + head + index | **v4 merged（Huihui + v4 adapter）**，同 16 层同命名；唯一能分辨新旧的是 `layers_index.json.src` 与每层 sha16（结构检查全绿也可能是旧权重 = 最危险坑） |
| `merged-layers/config.json` | **包内没有**（v3 靠 local_train.ps1:83-96 回退复制 base-meta 的 VL 包装 config） | **v4 必须自带 pin 过的 config**：`architectures=["Qwen3_5ForCausalLM"]`、无 `vision_config`、`text_config.architectures` 同步；否则 SplitSource 按 VL 结构派生 |
| `act-cache/*.pt` | 4,410 个（4388 语料口径） | **4,871 条**，且 `manifest.model` 必须是 v4 merged 路径（现存云端 act-cache-v4 的 manifest.model=base/Huihui ⇒ 作废重算） |
| `act-cache/` 分组目录 | re-train / forge-train / route-train / discipline-train / gen-train + 4 个 val | 必须与 **subsets-v4** 的分组名逐一对齐（`train_partial_lora.py --data-mix name:path` 的 name 就是这些目录名，对不上会静默少训） |
| `config.json` / `tokenizer*` | 包内没有，fix_pack 从 base-meta 补 | 同样从 `train/kitty-rev/deploy/base-meta/`（9 件 / 22,917,507 B）补，路径已在 fix_pack.sh 默认值里 |
| 包名 | `kittyrev-local-pack.tar` | 加 `-v4` 后缀，**不要覆盖 v3 包**（v3 是已交付证据） |

**三个"装错不报错"的坑**：act-cache 用旧缓存（条数/基座不符）· merged-layers 用 v3 的 16 层 · subsets 分组名与 --data-mix 不一致。三者都表现为"训练 loss 正常但能力不长"。

### 22.4b 三个数一条链（2026-10-22 19:00，data-verify 提出两式同值的疑问后拆解定稿）
```text
base 语料            large-mix-plus/train.jsonl                   = 4388 行
  Σ基座组            forge 480 + re 359 + route 292 + disc 383 + gen 100 = 1614
  rest               = 4388 − 1614 = **2774**

+ forge 补数 99（r3 60 + r4 19 + r5 20，forge4/forge5 批次）
  Σ组变              forge 579 + 其余 1134 = **1713**
  语料唯一行          = 4388 + 99 = **4487**
  rest 仍为          **2774**（补数全进 forge 组，不进 rest）

+ 384 条重复（forge train 行复制一次以增加曝光；make_subsets 按 content_hash 去重）
  raw 行数            = 4487 + 384 = **4871**  ← train_kitty 直读，不去重

⇒ 权威式：`rest 2774 = 4487 − 1713 = 4388 − 1614`（差 99 是补数）
          `raw 4871 = 4487 + 384`（384 只影响训练层，不影响 rest）
⇒ 3080 是"未去重且未剔 forge"的旧口径，属口径变化不是数据漂移 —— 别再当参照值
```

### 22.5 v4 训练曲线实测（2026-10-22 19:00，云端 train2.log 46 条记录）
```text
epoch 0.016  loss 2.796  entropy 1.513  acc 0.514  grad 3.750
epoch 0.033  loss 1.649  entropy 1.603  acc 0.635  grad 0.484
epoch 0.049  loss 1.370  entropy 1.701  acc 0.697  grad 0.457
epoch 0.723  loss 0.782  entropy 0.585  acc 0.855  grad 0.346
epoch 0.756  loss 0.654  entropy 0.576  acc 0.866  grad 0.272
epoch 0.772  loss 0.697  entropy 0.507  acc 0.880  grad 0.371
（256/915 步 · 19.5 s/it · ETA 22:27）
判读：loss 收敛正常 · grad_norm 0.27-0.37 健康（无爆炸）· acc 0.51→0.88
⚠ **entropy 单调下降 1.70 → 0.51，v3 终点是 0.2591（§6 记为 memory 型拟合）**
⇒ 风险：B 组 re60 的提升可能部分来自"背答案"而非"会用"
⇒ 处置：B 组判读必须加 **M9 记忆 vs 能力**：查 `re_detail[].contaminated` 条数
   · B 的 contaminated ≥3/60（5%）→ 结论必须写"部分提升来自记忆"
   · b−c 显著为正 **且** contaminated ≥3 → 「能力与记忆混淆，不可分离」，禁止写"能力显著提升"
   · 只有 b−c 为正 **且** contaminated ≤1 时，才可以写"提升不是来自记忆"
```

### 22.6 一处口径更正（2026-10-22 20:15，judge-ledger 在 run_B_verdict selftest 中发现）
```text
C 组 bench40 的 "4 条空答（i=3,13,19,36）" **表述不准**：
  · 产物 summary.n_empty 实测 = **0**（eval_bare 的 n_empty 只数 len==0）
  · 那 4 条实际是 **chars=17 的极短占位答**（f1≈0.01）
⇒ 正确表述：**极短占位答 4 条（chars=17）**；M8 判据 = `chars ≤ 20` 的条数，从 4 → 0-2 才算结构性改善
⇒ 影响：C-BASELINE-CARD / DELIVERY-PACKAGE / TONIGHT-INDEX 三处表述都要改（数字不动）
⇒ 教训：判据的名字必须与实测对象同名。写"空答"而去数 len==0，明天有人会在产物里一条也找不到。
```
```
```
```

## §23 接管后现场与存盘计划修订（2026-10-22 23:0x）

> 本节由 plan-optimizer 于 23:07 追加。**只追加，不改历史**：§1–§22 一字未动（自证 md5 见本节末尾）。
> 采集口径：`deploy/remote.py --cmd` 对 123.127.15.155，只读；时刻均为云端时刻。

### 23.1 现状三角（23:05:08–23:06:44 实测）

**已得（只读，勿重算）**
```text
训练      adapter out-v4/adapter/adapter_model.safetensors 159,452,256 B @22:20（md5 11d3d28e）
merge     merged/Qwen3.8-27B-kittyrev-v4 = 51G（du 实测 51G @23:05:08）
数据      subsets-v4 齐：13 文件 @18:33（12 subset + refusal_scan.json）
          tmp/mix/train-forge45.jsonl 6,547,311 B @14:47
工具链    $LC=/root/autodl-tmp/lc（树根即 llama.cpp 本体）
          $LC/build/bin/llama-quantize 17,856 B · llama-imatrix 225,328 B（均 @23:05）★已建成
          $LC/convert_hf_to_gguf.py（step3 正在用，pid 39056）
本地兜底  qwen3_8_27b_kittyrev_iq2s.ninfer 9,407,284,736 B · kittyrev-local-pack.tar 25,778,176,000 B（v3）
```

**已丢（本轮损毁，不可找回）**
```text
/tmp/lc 整棵树（llama.cpp 源码树 + gguf-py + convert 脚本）—— 随本轮清 /tmp 一并消失
  · 现存证据：ls -ld /tmp/lc → No such file（23:05:08）
  · 二次损失：/tmp/gguf-prefix-guard.py（step3 判据脚本）同批消失，find 零命中（23:05:30）
/tmp 下的 bf16 GGUF 三次半截产物（根分区 30G overlay ENOSPC）
```

**已重建（23:03–23:05，全部落数据盘）**
```text
$LC 整包（本地下载 38,449,221 B → put，md5 a4706331 双端一致）→ 解包即 llama.cpp 树（$LC/build 为构建目录）
gguf pip force-reinstall 0.19.0（原为指向已删 /tmp/lc/gguf-py 的悬空 editable）
step3 GGUF bf16 重跑：23:03:56 起，convert-bf16.log 自报 62% 33.5G/53.8G @223 MB/s（23:06:44），T≈23:08:15
```

### 23.2 三条新增硬约束（今晚新增，优先于任何旧表述）

```text
H1 禁 /tmp 写：任何临时/中间/脚本/软链产物一律落 $R=/root/autodl-tmp/kitty-rev 之下；
   守卫类脚本落 $R/tools/。**永不 `rm -rf /tmp/*`**（本案已因此损毁两次）。
H2 torch 锁定 2.6.0+cu124：llama.cpp 的 requirements 钉 torch==2.11.0，裸装会覆盖并毁掉 act-cache 重算能力
   ⇒ 装依赖必须 --no-deps，或先 `pip install -r … 2>/dev/null | grep -c torch==2.11.0` 拦截。
H3 工具链落数据盘 + 路径以实物为准：$LC/build/bin/llama-*（**不是** $LC/llama.cpp/build/bin）；
   数据根为嵌套双层 $KV=/root/autodl-tmp/kitty-rev/kitty-rev，$R 与 $KV 不可混用。
   `/tmp/lc` 软链**从未创建**（TASKPOINT 旧文与 TAKEOVER-BRIEF:38 该表述作废）。
```

### 23.3 重排后的时刻表（以 step3 完成时刻 **T** 为基准，不写死绝对值）

```text
T = step3 bf16 GGUF 收口（实测 T≈23:08:15；判据见 §23.5 假红风险）
T+0    P4 造 calib-v4.txt（524 chunks，源自 tmp/mix/train-forge45.jsonl；3m）★新增，旧表无此步
       ‖ 同时起 imatrix 与 act-cache（O1：CPU-bound 与 GPU-bound 并行，省 15m）
T+3    step4 imatrix（CALIB=calib-v4.txt + --force --gate）13m
T+16   step5a O8 腾盘（只删两个具名文件）1m
T+17   step5b IQ2_S 量化 22.5m  → 判据：张量数(iq2s)==张量数(bf16)，体积 ∈ [9.0e9,10.737e9)
T+40   step6 convert+inspect 19.5m（--name 含 -v4，输出 $R/ninfer-v4/，不覆盖 v3）
T+52   step7 act-cache 应已收口（起于 T+0，15m，T+15 完成）→ 判据 .pt==4871 严格等号
T+60   回传 .ninfer 16m —— **交付① ≈ T+76**
T+61   拆层 1.2m + pack 6.8m → T+69；本轮**不删 merged**（O2，99G avail 足够）
T+76   回传 pack 40m —— **交付② ≈ T+116**
之后   本地 pack_accept_v4.sh 五组断言 + verify_local_pack --expect-pt 4871 + 本机 ninfer 实跑出话
```

### 23.4 本轮 4 份子代理产物索引

| 产物 | 行数 | 内容 | 状态 |
|---|---|---|---|
| `logs/v4/TAKEOVER-BRIEF.md` | 132 | 接管确认：目的/两交付/现状/修复/执行序/三条高危线 | ✅ 23:04 |
| `logs/v4/DELIVER-RESUME-PLAN.md` | 89 | step3→10 执行序 + 双路径排班（模式 A/B） | ✅ 22:54（其 §4 时刻已被 §23.3 取代） |
| `logs/v4/PLAN-DELTA.md` | 27 | 17 条「文档 vs 现场」对账（6 类全覆盖） | ✅ 23:07 本轮 |
| `logs/v4/PLAN-AUDIT-R11.md` | 60 | 方向判定 DRIFT + 5 条纠偏 + 时间账 + 3 条优化 + 1 条自我更正 | ✅ 23:07 本轮 |

### 23.5 §23 引入的两条判据修订（不改铁律，只改判据强度）

```text
① step3 体积判据：原「51.5G ±5%」**作废** —— 实测真实总量 53.8G（convert 自报），余量只剩 0.5%，会假红。
   改为「张量数 == len(weight_map) ∧ ≥53.0G ∧ ≤55.5G ∧ bad_prefix=0」。
② 交付① 判据顺序：`data[0].id` 字符串 → 结构 Qwen3_5ForCausalLM → 体积区间 → 本机实跑。
   理由：半截 .ninfer 也落在体积区间内，id 串才是一次性判别。
```

### 23.6 追加式编辑自证（附录式编辑，历史段零改动）

```text
改前：head -n 922 TASKPOINT.md | md5sum = 0e6b2abd0ebb88a09f3a730662aa4b84
改后：head -n 922 TASKPOINT.md | md5sum = 0e6b2abd0ebb88a09f3a730662aa4b84
断言：两者相等 ⇒ §1–§22（原 922 行）一字未改，§23 为纯追加。
（改前文件行数 922；本节即原文件末尾之后的首段。）
```

---

# §24 最新断点（2026-10-24 01:10）—— v4 交付① 卡在"权重本身是错的"

> 本节为纯追加，§1–§23 全部保留。**新会话只读本节即可接续**（其余各节当历史证据）。

## 24.1 一句话现状

```text
v4 的 .ninfer 已经做出并回传到本机（10,210,440,704 B = 9.51 GiB，md5 95971f6e557ac1f3acd2481582e01697），
但**判据七实测为多语种乱码**；同一引擎同题跑基线 .ninfer 输出正确 → 根因是 merged-v4 的权重本身错
（merge.py 用 transformers 加载混合架构，绝大多数权重没加载，写出随机/零值）。
⇒ 正确路径：重下真基座 55.6 GB + **张量级 merge**（不用 transformers）→ 重走导出→量化→splice→convert→回传→判据七。
```

## 24.2 本轮已完成（全部有数字/命令验证）

| 环节 | 结果 | 验证方式 |
|---|---|---|
| 基座重下（第二轮） | 18/18 片，total **55,563,006,216 B** | 每片 `size == HF API tree.json 的 size` 且 `safe_open()` 可打开 → `[G1-INTEGRITY] PASS` |
| G2 merge（**错误做法**） | merged-v4 = 12 shard / **53,812,199,499 B** | 产物存在但**内容错**（见 24.4） |
| G4 导出 bf16 | **53,808,282,208 B**，851 张量，judge8 PASS | 用自修写通道 `tools/convert_gguf_safe.py`（官方 numpy `tofile` 会假报 ENOSPC） |
| GDN 取数 | **432/432 张量 · 11,124,159,248 B** | 本机 16 路按 safetensors header 偏移 Range 抠取，落 `tmp/_gdn/model.safetensors`，`safe_open` 432 keys |
| G3 回填 | **zero 张量 = 0 / 432** + 18 条抽检 `max|Δ|=0` | `tools/gdn_refill.py`（accept-fix 修好 F32 槽位 dtype 对齐 + ssm_a 用 `-exp(A_log)` 比对） |
| G5 IQ2_S 量化 | **9,381,161,824 B** | imatrix 496 条 + 128 条 `--tensor-type ssm_*=q8_0`；语法是 `--imatrix X [tt...] <in> <out> IQ2_S 64`（threads 是**位置参数**） |
| G6 splice | **9,729,631,968 B** · n_t=866 · blk.64=15 · arch=`qwen35` · block_count=65 | `tools/splice_new.py` + 自检打印 |
| G7 convert | **806 objects · 10,210,440,704 B** | 含 `proposal/head` (gguf_q5_k 131072×5120) 与 `proposal/token_ids` (int32 131072) |
| 回传 | 本机同尺寸 · md5 **95971f6e557ac1f3acd2481582e01697** 双端一致 | `deploy/get_multi.py --streams 48` |
| **判据七** | **FAIL（乱码）** | 见 24.3 |

交付②（v4 内容包）仍在本机：`train/local-pack/kittyrev-local-pack-v4.tar` = 27,320,197,120 B，md5 `1c6cb2ffc9a0e8f374a289e3065a63f1`（5/5 验收 + verify_local_pack PASS）。

## 24.3 判据七实测（对照实验，决定性证据）

```text
同一引擎（ninfer-csunx + run-engine.ps1 -NoVision）、同一提示词（PE FileAlignment/SectionAlignment）、
同一请求体（enable_thinking=false，否则 400 token 全被 reasoning 吃掉、content 为空）：

基线 ninfer-27b-kv-stream-3arch-20261019/model/Huihui-…-IQ2_S-mtp.ninfer
  → content_chars=204 cjk=96 ratio=0.471 bad_run=0 reasoning_tokens=0 finish=stop
  → 回答正确：「FileAlignment(0x200) 是磁盘物理存储粒度…SectionAlignment(0x1000) 是内存逻辑对齐…」⇒ **可读中文**

我们 final6.ninfer（G1–G5 全绿的那个）
  → content_chars=1713 cjk=743 ratio=0.434 bad_run=6 reasoning_tokens=0 finish=length
  → 「öt吉祥如意甘于按照规定神兵摸了…」⇒ **多语种词沙拉**
```

**结论**：转换链（导出/回填/量化/splice/convert）全部正确，坏的是 **merged-v4 的张量值**。

## 24.4 根因（比"192 个 GDN 张量为零"更严重）

```text
merge.py L63-73：
  model = AutoModelForCausalLM.from_pretrained(base, dtype=bf16, device_map="cpu", low_cpu_mem_usage=True)
  model = PeftModel.from_pretrained(model, adapter); model = model.merge_and_unload()
  model.save_pretrained(dest, safe_serialization=True, max_shard_size="5GB")

对 Qwen3.5 混合架构（64 层，linear_attention(GDN)/full_attention 交替），transformers 这一版
不认 `linear_attn.*` 参数名 → 这些权重组装时被建成空/零张量；`low_cpu_mem_usage=True` 下
未匹配的 key 也不会报错。实测证据：
  · merged-v4 的 linear_attn 抽样 72 个，**全零 60 个**
  · 回填 GDN 后 zero=0，但**模型输出仍是乱码** ⇒ 其它模块（attn/mlp/embed）也是错值（随机初始化）
  · judge8 的"非零率 0.998"判据对随机初始化同样成立 ⇒ 该判据不能证明权重正确
```

**已丢弃的错误路线**（不要再走）：
1. ~~只补 GDN 432 槽位~~ → zero=0 但整体仍乱码（本轮已实测）
2. ~~用 `convert_gguf_safe` 修导出器~~ → 导出器本身没问题（judge8 与张量数都对）
3. ~~对超写分片用 `curl -C -` 续传~~ → 内容错位（见 24.8）

## 24.5 下一步（可直接执行，按序）

```bash
# 步骤 A：重下真基座 55.6 GB（本机 16 路 Range，实测 5.6 MB/s ⇒ 约 2.7 h；断点可续）
#   现状：tmp/_base 已清空，需要 tree.json 与 shards.txt（可从云端 /tmp/tree.json get 回来）
cd D:/BaiduNetdiskDownload/Local-AI/train/kitty-rev
python deploy/remote.py --get /tmp/tree.json tmp/_base/tree.json
bash tools/dl_base8.sh            # 脚本已带：N=6/16 路、-4 强制 IPv4、--speed-limit、逐片 size==want、失败重试

# 步骤 B：张量级 merge（**不要用 merge.py / transformers**）
#   待写：tools/tensor_merge.py
#   逻辑：逐 shard 读 base safetensors → 对 target_modules(q/k/v/o/gate/up/down_proj) 做
#         W' = W + (B@A) * (lora_alpha / r)   # r=16, alpha=32 ⇒ scale=2.0
#         非 target 张量（含 linear_attn.*）**原样复制字节**
#   校验：linear_attn 抽样 abs().max()>0；与 base 同名字节相等

# 步骤 C：重走已验证通过的链（命令与参数见 24.2，全部已跑通过一次）
#   导出 bf16 → gdn_refill(预期 zero=0，因为 GDN 已原样复制) → IQ2_S → splice_new → convert
#   → 回传 48 流 → 判据七（threshold 已修正：cjk>=50 & ratio>=0.35 & rt==0 & bad_run<3）
```

## 24.6 新增雷区（只增不减；与 §9 并列有效）

- **坑：用 `AutoModelForCausalLM` + peft 对混合架构做 merge**；原因：`linear_attn.*` 不在模型参数表里，`low_cpu_mem_usage=True` 不报错，直接写出零/随机值，**下游全部闸门都会绿**；正确做法：**张量级合并**（base 字节复制 + 仅对 LoRA target 做 `W + B@A*scale`），或在 merge 后立刻做"三查"：`linear_attn 抽样非零` ∧ `embed 与 base 逐元素相等` ∧ `引擎实问一句说人话`。
- **坑：拿"非零率/结构判据/张量数"当权重正确性的证据**；原因：随机初始化同样非零、结构同样齐全（本轮 G1–G7 全绿但模型是乱码）；正确做法：**判据七是唯一硬门**，且必须**同引擎同题跑基线做对照**（基线说人话、新品说人话才算过）。
- **坑：`reasoning_tokens` 吃满导致 content 为空**；原因：引擎默认 `-ReasoningEffort high`，400 token 全进 reasoning，`finish=length`、content="" ；正确做法：请求体加 `"chat_template_kwargs": {"enable_thinking": false}`，并把 `max_tokens` 提到 ≥600。
- **坑：`llama-quantize` 参数顺序**；原因：`-t 64` 会被当成 ftype（报 `invalid nthread '-t'` / `invalid ftype <输入路径>`）；正确做法：`--imatrix X [--tensor-type ...]* <in> <out> IQ2_S 64`（线程数是**位置参数**，放最后）。
- **坑：splice 输出目录不存在**；原因：`splice_new.py` 直接 `open(out,'wb')` 不建目录 → `FileNotFoundError` 被误读成"拼接逻辑坏"；正确做法：先 `mkdir -p gguf/mtp-spliced`。
- **坑：判据七用"CJK>50%"会冤枉正确回答**；原因：正常中文技术答里 PE/RVA/0x1000 等英文术语占比高，实测基线 ratio=0.471；正确做法：`cjk>=50 字 ∧ ratio>=0.35 ∧ bad_run<3 ∧ reasoning_tokens==0`（本轮已改 `tools/judge7_v4.py`）。
- **坑：本机并发 curl 过多触发 `getaddrinfo() thread failed to start`**；原因：Windows 上 10+ 个 curl.exe 并发耗尽 DNS 线程，表现为"下载静默失败、日志 0 字节"；正确做法：并发 ≤8 且必须 `-4`（强制 IPv4），失败日志要落盘（不要 `>/dev/null 2>&1` 全屏蔽）。
- **坑：官方 `convert_hf_to_gguf.py` 的 numpy `tofile` 在本机假报 ENOSPC**；原因：`OSError: Not enough free space ... after offset 7.9G/26.2G/32.3G`，而 `df` 还有 94–124 G；正确做法：一律用 `tools/convert_gguf_safe.py`（写前物化 + 8 MiB 分块 + judge8）；注意 `LazyNumpyTensor.to_eager` 是 **classmethod**。
- **坑：`screen -dmS` 在本环境会静默失败**（`No Sockets found`）；正确做法：长任务用 `setsid nohup ... < /dev/null &` + 日志落盘，进度只认云端文件产物。
- **坑：为腾盘删掉"还要用的源"**；原因：本轮为省 55 G 删了 base-hf，结果 merge 证明是错的、必须重下（代价 2.7 h）；正确做法：删前查 `PROTECTED`（base / merged / adapter / act-cache / cfg-vision / ref），只删可重生成的中间件。

## 24.7 关键文件与脚本（本轮新增/修改，均在 `train/kitty-rev/` 下）

| 文件 | 作用 |
|---|---|
| `tools/dl_base8.sh` | 本机 N 路 Range 下基座（逐片 size==权威值，失败重试；需先有 `tmp/_base/tree.json`+`shards.txt`） |
| `tools/fetch_gdn2.py` | 从 HF 分片按 header 偏移抠指定张量 → 单个 safetensors（本机 16 路成功，432/432） |
| `tools/upload_par.py`（= `up_par.py`） | 多线程分块上传（每块校验远端 size，坏块重传；本机→云端 9.7 MB/s 峰值） |
| `tools/gdn_refill.py` | 按 432 槽位回填 + 逐槽位回读（zero 必须 0）+ 9 类各 2 个抽检（TOL 1e-3） |
| `tools/night_run.py` | 云端无人值守总控：G1→G5 逐门推进 + `.markers/<门>.ok`（断点续跑：`--from G3`） |
| `tools/convert_gguf_safe.py` | 自修写通道（绕开官方 numpy tofile 假 ENOSPC）+ judge8 抽样非零 |
| `tools/splice_new.py` | IQ2_S + MTP 拼接（866/15/arch=qwen35/bc=65 自检） |
| `tools/judge7_v4.py` | **判据七**：实问 + 字数/中文占比/乱码连串/`reasoning_tokens` 四判据（阈值已按 24.6 修正） |
| `tools/remote_clean.sh` | 云端环境净化（杀残留/清中间件/只读现状 + merged 的 GDN 零张量快检） |
| `logs/v4/PITFALLS.md` | 12 条踩坑与避坑方案（传输/转换/权重三层） |
| `logs/v4/NIGHT-RUN.log` `logs/chain3.out` `logs/chain4.out` | 各门执行流水（含每门判据数字） |

云端关键产物（`/root/autodl-tmp/kitty-rev/`）：`gguf/v4-bf16.gguf`(53.8 G，已回填 zero=0) · `gguf/v4-iq2s-851.gguf`(9.38 G) · `gguf/mtp-spliced/v4_mtp_s.gguf`(9.73 G) · `ninfer-v4/qwen3.8-27b-kittyrev-v4-swift1.5-gsq-rco-abliterated-iq2s-mtp.ninfer`(10.21 G) · `gdn-only/model.safetensors`(11.12 G，432 张量真值，**可复用于下一次 merge**)。

## 24.8 验证方式（每步的"过了"标准）

```text
下载  18 片 size == tree.json size（等号）且 safe_open 可开；整包 = 18 片之和（header 开销 150,312 B 正常）
merge 每个 linear_attn 张量 abs().max()>0；target 模块 delta 范数非零；非 target 与 base 字节相等
导出   851 张量 / 53.8 G / judge8 PASS
回填   写后 zero == 0（逐槽位）+ 抽检 max|Δ| == 0
量化   IQ2_S 851 张量 / 9.0e9–1.0737e10
拼接   866 / blk.64=15 / arch=qwen35 / block_count=65
convert 806 对象 / ≤10 GiB / 含 proposal/head + proposal/token_ids
回传   双侧 md5 一致
判据七 **同引擎同题：基线说人话 + 新品说人话**（cjk>=50 ∧ ratio>=0.35 ∧ bad_run<3 ∧ rt==0）
```

## 24.9 恢复指令

```text
新会话打开本项目 → /resume → 读本节 §24 → 从 24.5 步骤 A 开始。
若只想先确认现状：`cd train/kitty-rev && python tools/judge7_v4.py`（需引擎已用目标 .ninfer 起在 1234）。
引擎启动（本机）：
  & 'C:\Program Files (x86)\PowerShell\7\pwsh.exe' -NoLogo -NoProfile -File 'D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx\run-engine.ps1' \
      -ModelFile '<abs .ninfer>' -NoVision
```

## 24.10 更新历史

- 2026-10-22 10:35：v3 交付完成，v4 换基座开始（§1–§7）
- 2026-10-22 23:07：takeover 后重排（§23）
- **2026-10-24 01:10：v4 交付① 全链跑通但判据七判定为乱码；根因锁定 merge 权重错；下一步=重下基座 + 张量级 merge（§24）**
- **2026-10-24 06:10：§24 的三步全部完成，判据七 PASS，交付① 达成（见 §25）**

---

# §25 v4 交付① 完成（2026-10-24 06:10）

> 详细报告：`train/kitty-rev/logs/v4/DELIVERY-REPORT-2026-10-24.md`
> 本轮把 §24 的三个待办（重下基座 / 张量级 merge / 重走链）全部做完，并**判据七第一次 PASS**。

## 25.1 交付件

```text
train/local-pack/qwen3.8-27b-kittyrev-v4r-iq2s-mtp.ninfer
  10,313,291,264 B = 9.605 GiB < 10 GiB ✓
  md5 87e10860249b538bd41b41f8ff2cde47（本地 == 云端 meta.json，全文件）
  + .conversion.json 307,735 B
判据七（本机 5070 Ti）:
  [G7] content_chars=192 cjk=82 ratio=0.427 reasoning_tokens=0 bad_run=0 → PASS
  答对了 PE 对齐实质，并主动给出「用 kitty_patch 校验落盘」的训练痕迹
引擎自证: engine ready | qwen3.8-27b-kittyrev-v4r-iq2s-mtp | weights 9.16 GiB
```

## 25.2 与 §24 的差异（关键：merge 换实现）

```text
§24 结论：merge.py 用 transformers → linear_attn 不在参数表 → 随机/零值 → 全门绿但乱码
本轮     ：tools/tensor_merge.py 张量级合并
           · 只对 7 个 target_proj 做 W + B@A*(alpha/r)=2.0
           · 其余张量（linear_attn / embed / norm / MTP）**原始字节复制**
           · header 原样复用（同名/同 shape/同 dtype/同序）
证据     ：target 256/256 PASS · delta 全非零 · 非 target 复制 940 · HIT |delta| 0.7–7.2
```

## 25.3 九门实测（全部有产物与数字）

```text
G1 18片/55,563,006,216B/1199张量/结构18/18
M0 55563006216B   M1 54,657,734,112B (866张量, 含blk.64×15)
M1.5 cjk=151 latin=211 gen_len=489 rc=0  ← 权重正确的决定性证据
M2 29,047,084,512B (q8_0)   M2.5 ppl=1.5675 (下限门, 见降级项)
M3 27,300,192B (GGUF v3 / 1984条目, chunks取证缺失)
M4 9,832,482,528B magic=GGUF rc=0 2.88BPW
M5 copied n64=15 (跳过 splice, blk.64 已在)
M6 806 objects / 9.605 GiB
```

## 25.4 本轮新增的 8 个坑（都写进报告 §3）

```text
1 -no-cnv 在本 build 不存在 → 用 -st --single-turn + --no-display-prompt
2 M2 用 convert $MERGED 而 --free-merged 已删它（自噬）→ 改 llama-quantize bf16→q8_0
3 ppl 用 -ngl 99（27GiB > 24GiB 卡）→ 改 -ngl 0
4 **M4 旧判据只看体积 → rc=1 残体被记 PASS** → 加 rc==0 + magic==GGUF 双断言
5 imatrix 不覆盖 MTP(blk.64) → IQ2_S bail out → --tensor-type blk.64.*=q8_0（15条）
6 inspect_safetensors 聚合只算打印子集 → 76张量片全假 MISMATCH
7 COPY_EXTRA 写 "index.json"（真名 model.safetensors.index.json）→ merge 不拷 index
8 M5 在 M4 未收口时抢跑 → 读到半成品 not gguf
```

## 25.5 未解决 / 需操作者处理

```text
① 云端 4090 未能自动关机：容器 PID 1 受内核信号保护，
   kill -TERM/-9 1、poweroff -f、halt -f、systemctl poweroff 全部无效
   ⇒ 需在 AutoDL 控制台手动点"关机"
② M3 chunks 取证缺失（chain 的 run() 只 tail 尾部）—— 下轮应把完整输出落 logs/v4/_raw/
③ M2.5 ppl 门设计缺陷（calib 来自训练语料）—— 下轮换域外文本
④ 交付②（local-pack-v4）沿用上一轮的 27.3 GB 件，本轮未重做
```

## 25.6 下轮起步

```text
若要做 v4.1（意愿层）：见 §13，数据在 data/intent3/，配比见 §13.6
若要重跑：chain_repair.py --from <门> 可断点续跑（.markers-r/*.ok）
判据七复测：起引擎 → python tools/judge7_v4.py
```

---

# §26 V5 执行方案已定稿（2026-10-24 11:50）

> ⚠ **下轮开工第一件事：读 `train/kitty-rev/logs/v5/TEAM-PLAN-V5.md` 的 §0。那是唯一执行路径。**

## 26.1 唯一正确路径（一句话）

```text
merged bf16 HF 权重 + imatrix  →  convert(recipe=qwen3_8_27b_imatrix)  →  .ninfer（GSQ-RCO）
```

**不是** v4 那条 `bf16 → llama-quantize IQ2_S → splice → convert(qwen3_8_27b_gguf)`。

## 26.2 为什么换路（已实锤）

```text
GSQ 格式（q2_g64_fp16 / q8_g32_fp16）不是"训练出来的"，是 GGML Q2_0 / Q8_0 块的直通容器
  ← gguf_blocks.py:288 q2_native_source() 原文：type_id != GGML_Q2_0 就报错，然后直接搬 18 字节块
ninfer 自带 Qwen3.8-27B 的 GSQ-RCO recipe：
  official_recipes.py: qwen3_8_27b / qwen3_8_27b_q6 / qwen3_8_27b_imatrix
  qwen3_8_27b_imatrix 注释原文："Qwen3.8-27B sized for one 24 GB card: grouped_search with signed scales"
dry-run 实测：979/979 参数覆盖，0 missing，recipe ran OK（见 logs/v5/DRYRUN-GSQ-RCO-EVIDENCE.md）
```

## 26.3 成本

| 路径 | 内容 | 时间 | 成本 |
|---|---|---|---|
| A | 只换量化（GSQ-RCO） | 3.2-3.6 h | ¥7-8 |
| B | 量化 + V5 意愿层 | 6.5-7.5 h | ¥14-16 |

余额 ¥14 → A 够，B 需充值。

## 26.4 三个锚点（防止执行中走偏）

```text
① 方案 §0.4「路径锁定」：明列 5 条禁止（尤其"不许再用 llama-quantize + qwen3_8_27b_gguf"）
② 团队每张执行卡开头必须抄一遍 26.1 那行
③ 每步 PASS 必须三者同时成立：rc==0 + 内容校验 + 尺寸
```

## 26.5 ★硬性规定：每完成一步必须做 PR（计划复核），未做不进下一步

> 操作者 2026-10-24 11:30 定稿。违反视为未交付。

```text
每完成 T1/T2/T3/T4/T5/T6 任一步：
  ①本步结果 vs §0 预期（带数字）
  ②计划是否仍正确（§0.5 三个假设逐条判）
  ③下一步的命令+判据+耗时写全
  ④是否需要改计划（改则同步改 TEAM-PLAN-V5.md）
→ 落盘 logs/v5/PR-T<n>.md（模板 logs/v5/PR-TEMPLATE.md）
→ 结论 = PROCEED 才许起下一步；HOLD/REVISE 停
PR 由 lead 决策 + reviewer 独立给结论（两份结论不许合并成一行）
本步 PASS 后 5 分钟内未出 PR → 本步视为未收口
```

**为什么**：v4 那一夜 3 次返工全是"做完就走、没回头验计划"（M2 自噬 / M4 假 PASS / M5 抢跑）。
每一次都不是执行错，是**计划与现实的偏差没被复核**。

**违规判据**（自查）：
```text
✗ T(n+1) 已开始但 PR-T(n).md 不存在
✗ PR 的 Q2/Q3 空着或只写"正常"
✗ PR 说计划有变但 TEAM-PLAN-V5.md 没同步改
✗ 连续两步 PR 无 reviewer 独立结论
```

## 26.6 每一步的 PR 落盘位置

```text
logs/v5/PR-T1-G1.md          （base 下载 + 完整性）
logs/v5/PR-T2-merge.md       （张量级合并）
logs/v5/PR-T3-convert.md     ★ 最关键（GSQ-RCO 是否成型）
logs/v5/PR-T4-verify.md      （判据七 + kitty7）
logs/v5/PR-T5-train.md       （仅 B 路径）
logs/v5/PR-T6-ship.md        （回传 + 关机）
```

## 26.7 未验证项（执行时暴露，处置见方案 §5 D1/D2）

```text
1 imatrix 格式（GGUF v3 容器 vs legacy .dat）
2 MTP 来源（--components text,mtp 依赖 merged 里 mtp 张量）
3 输出体积（GSQ 混合可能 10-12 GB，超 10 GiB 要退 recipe）
```


