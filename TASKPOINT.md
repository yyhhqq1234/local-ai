# TASKPOINT — 项目级任务断点

> 保存时间：2026-10-21 16:25（UTC+8）
> 项目根目录：D:\BaiduNetdiskDownload\Local-AI
> 分支/版本：master @ dc44148（"docs: 新增后训练可行性指南（docs/06）"），工作区有未提交改动

## 1. 任务目标
- 一句话目标：给部署中的 `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer` 做**逆向工作台（kitty）能力后训练**，数据优先适配 kitty 逆向工作台，训完能回炉成可部署的 `.ninfer`。
- 验收标准：
  - [ ] 27B QLoRA 训练跑通（100 步冒烟 loss 下降、无 NaN、无 OOM）
  - [ ] 训练后 adapter 能合并 → `tools.convert` 产出 `.ninfer`（787 objects 级结构自检通过）
  - [ ] 新 `.ninfer` 能被 `ninfer-serve` 加载（`/v1/models` 200 + 一次真实推理）
  - [ ] 行为判据集 `eval_kitty.py` 分数高于训练前基线（27B 基线 3/23 = 13%）

## 2. 背景与现状
- 部署模型：`ninfer-27b-kv-stream-3arch-20261019/model/Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer`（9.53 GiB，IQ2_S，MTP 已开）。
- 推理引擎：NInfer（`ninfer-csunx`，`ninfer-serve.exe`），OpenAI 兼容 `/v1/chat/completions`，默认 1234 端口；**操作者要求不主动拉起引擎**。
- 本机硬件：RTX 5070 Ti Laptop 12 GB / RAM 31.5 GB / D 盘约 230 GB 可用。12 GB 显存**装不下** 27B 4bit（12.6 GiB），已把 8 条本地路径试穿（详见 `train/kitty-rev/docs-12gb-feasibility.md`），结论：本机不可行，必须换 24 GB 卡/云。
- 现状：操作者已租 **AutoDL RTX 4090 24G**（北京 B 区 288 机，镜像 PyTorch 2.5.1/Python3.12/CUDA12.4，数据盘 150 G，¥2.18/h，余额 ¥50）。GPU 目前 0% 占用，**训练尚未开始**。
- 变更记录：原计划本机 WSL2 → 改为租 24 GB 云卡（因 AutoDL 4090 有货）；云上又因镜像 torch 2.5.1 太旧改为升 torch 2.6.0+cu124。

## 3. 总体计划
1. 数据工程：契约抽取 + 真实轨迹 + 手工知识库 + 开源推理链混合（**已完成**，`data/large-mix` 3908 条）。
2. 环境：本机训练栈（已完成）；云上 4090 训练栈（**进行中**，差 cusparselt）。
3. 基座：27B bf16 下载（本机已完成；云端**已完成** 52 G/18 分片）。
4. 冒烟：27B QLoRA 100 步（待办，云上）。
5. 正式训练：3 epoch（待办）。
6. 回炉：merge → tools.convert → .ninfer → 结构自检（转换器已在本机验证过 27B base，云端待做）。
7. 部署验证：起引擎验 `/v1/models` + 真实推理（需操作者允许启动引擎）。
8. 评测：`eval_kitty.py` 前后对比 + `eval/bench` 主流测试集。

## 4. 团队模式
- 是否采用团队模式：**曾尝试 AgentTeams，但本 profile 不可用**——两次建队（`kitty-rev-posttrain`、`kitty-rev-full-flow`）所有成员均 spawn 失败：`agent-teams: provider "spawn" cannot apply a member persona`。已归档两个团队对象。
- 实际替代：并行 `subagent` + 后台作业。已交付的子 agent 任务：
  - 训练环境验真（PASS，产出 `logs/ENV-STATUS.md`）
  - 27B 基座下载与校验（PASS，产出 `logs/DOWNLOAD-STATUS.md`，含 Range 续传修复）
  - GGUF→.ninfer 转换器获取（PASS，产出 `train/tools/ninfer-convert/` + `logs/CONVERTER-STATUS.md`）
- 下次继续点：无需团队，Captain 单线在云实例上推进。

## 5. 步骤规划
| # | 步骤 | 负责人 | 状态 | 备注 |
|---|------|--------|------|------|
| 1 | 契约抽取（64 工具/66 OP/12 transition/28 错误码） | Captain | 已完成 | `scripts/extract_contracts.mjs` |
| 2 | 数据构造（自有 2736 + 开源 1172 = 3908） | Captain | 已完成 | `data/large-mix`，质检 PASS |
| 3 | 本机训练栈（torch 2.9.1+cu130 / tf 5.20.2 / bnb 0.50.2） | Captain+subagent | 已完成 | `train/.venv` |
| 4 | 本机 8B 冒烟（验证管线） | Captain | 已完成 | loss 3.898→2.484；混数据 2.995→1.711 |
| 5 | 本机 12 GB 可行性穷举（8 条路径） | Captain | 已完成 | 结论不可行，见 `docs-12gb-feasibility.md` |
| 6 | 云实例环境（torch 2.5.1→2.6.0+cu124） | Captain | 进行中 | 差 `nvidia-cusparselt-cu12==0.6.2` |
| 7 | 云上 27B 基座 | Captain | 已完成 | `/root/autodl-tmp/kitty-rev/base/Qwen3.8-27B` 52 G / 18 shards |
| 8 | 云上 100 步冒烟 | Captain | 待办 | 依赖 #6 #7 |
| 9 | 3 epoch 正式训练 | Captain | 待办 | `--ctx 2048 --bs 1 --ga 16 --all-gpu` |
| 10 | merge + convert + inspect | Captain | 待办 | 云端跑，产物 16 G |
| 11 | 引擎加载验证 | 操作者批准后 | 待办 | 需启动 ninfer-serve |
| 12 | 评测对比（kitty 判据 + 主流 bench） | Captain | 待办 | 基线 27B 3/23 |

## 6. 已完成步骤（已验证事实）
- [x] 契约抽取：`node scripts/extract_contracts.mjs` → tools=64 / ops=66 / transitions=12 / errCodes=28 / bridge v0.2.9（验证：脚本输出计数）。
- [x] 数据构造：`run_expand.py` + `gen_kb.py` + harvest → `data/large`（2736/304/48），`data/large-mix`（3908），`validate_dataset.py` VERDICT: PASS（struct/dup/contract/tool_call/over_ctx 全 0）。
- [x] 本机训练栈：`train/.venv` → torch 2.9.1+cu130 / cap (12,0) / tf 5.20.2 / peft 0.21.2 / trl 1.16.0 / bnb 0.50.2（验证：三条 import + capability 命令）。
- [x] 本机 8B 冒烟：`train_kitty.py --size 8b --max-steps 20` → loss 3.898→3.154→3.081→2.484，adapter 落盘（验证：日志 `train/logs/smoke-8b-3.log`）。
- [x] 混合数据 8B 复跑：3908 条 → loss 2.995→1.711，EXIT=0（日志 `smoke-8b-mix.log`）。
- [x] 27B 基座（本机）：18 shards / 51.75 GiB / 1199 tensors / index 一致（`logs/DOWNLOAD-STATUS.md`）。
- [x] 转换器：`Neroued/ninfer` 源码（ghfast.top 代理）+ 5 处 Windows 补丁 → `tools.convert --help` 通过；**27B base 实转成功**：`train/ninfer/qwen3_8_27b_base.ninfer` 16.35 GiB / 787 objects / 783 tensors / 123 s，`inspect` 自检通过（`logs/CONVERTER-STATUS.md` §9）。
- [x] 开源推理链：NuminaMath-CoT 400 / TIR 389 / OpenThoughts 1500（截断）/ ToolACE 1200 / LIMO 150（`REASONING-DATA.md` §10）。
- [x] 云端基座：52 G / 18 shards（ModelScope 下载，比 hf-mirror 快 3–4 倍）。

## 7. 进行中 / 下一步（新对话先干这个）
- 当前卡点：云端 `import torch` 报 `ImportError: libcusparseLt.so.0` —— torch 2.6.0+cu124 已装好，但缺 `nvidia-cusparselt-cu12==0.6.2`（150 MB）。GPU 0% 是因为训练还没开始，不是故障。
- 下一步动作（可直接执行，SSH 到 `ssh -p 35299 root@connect.bjb1.seetacloud.com`，密码见操作者提供）：
```bash
/root/miniconda3/bin/python -m pip install "nvidia-cusparselt-cu12==0.6.2" -i https://mirrors.aliyun.com/pypi/simple/
/root/miniconda3/bin/python -c "import torch;print(torch.__version__,torch.cuda.is_available(),torch.cuda.get_device_capability(0))"
# 期望 2.6.0+cu124 True (8, 9)
cd /root/autodl-tmp/kitty-rev
/root/miniconda3/bin/python kitty-rev/scripts/validate_dataset.py --dir kitty-rev/data/large-mix --ctx 2048 | tail -3
nohup bash cloud/run_autodl.sh smoke > /root/smoke.log 2>&1 &
tail -f /root/smoke.log
```
- 待验证假设：
  - torch 2.6.0+cu124 与 transformers 5.20.2 兼容（本机是 2.9.1+cu130 验证过，2.6 未验）
  - 24 GB 上 `--ctx 2048 --bs 1 --ga 16 --all-gpu` 不 OOM（估算峰值 18–20 GiB）
  - 云端 `merge.py` 能否吃下 54 GB（RAM 120 GB，应该可以）

## 8. 待办步骤
- [ ] 装 cusparselt → 验 torch → 起 smoke（100 步）
- [ ] smoke 通过后跑 `full`（3 epoch，4090 约 6–10 h）
- [ ] `merge`（合并 54 G）→ `tools.convert` → `.ninfer`（16 G）→ `inspect` 自检
- [ ] 只回传 adapter + `.ninfer`，然后关机省费
- [ ] 引擎加载验证（需操作者批准）
- [ ] `eval_kitty.py` 前后对比 + `eval/bench` 主流测试集
- [ ] 若 27B 结果不满意：用 DPO（48 对）再对齐一轮

## 9. 雷区（进行时必须避开）
- 现象/坑：云端直接 `pip install "transformers>=5.8"` 后 `import transformers` 报 `NameError: name 'nn' is not defined`；原因：镜像 torch 2.5.1 太旧，transformers 5.x 需要 torch ≥2.6；正确做法：先升 torch 到 2.6.0+cu124（复用镜像已有的 cu12.4 nvidia 库），再装 transformers。
- 现象/坑：`torch==2.9.1+cu128` 装完 import 报 `libcusparseLt.so.0 缺失`；原因：cu128 版要一整套 cu12.8 nvidia 库（cudnn 706 M 等 3 GB），而镜像只有 cu12.4；正确做法：用 **2.6.0+cu124**（依赖几乎全命中）。
- 现象/坑：`pip install torch` 从 download.pytorch.org 在 AutoDL 上卡住不动（triton 170 MB 十分钟无进展）；原因：该源被限速/阻断；正确做法：用 `https://mirrors.aliyun.com/pytorch-wheels/cu128/`（cu124 同理）当 find-links，或直接 curl wheel 后本地 `--no-deps` 安装。
- 现象/坑：hf-mirror 在 AutoDL 只有 2–4 MB/s，52 G 要 4 小时；原因：跨境+单连接限速；正确做法：改用 **ModelScope**（`modelscope download --model Qwen/Qwen3.8-27B --local_dir ...`），9–13 MB/s。
- 现象/坑：用 `pkill -f 'pip install torch'` 杀进程会把执行命令的 shell 自己也杀掉（命令串里含同样字符串），导致"无输出/日志文件消失"；正确做法：用带方括号的模式 `pgrep -f 'torch==2[.]9'` 或先取 PID 再 `kill`。
- 现象/坑：SSH 里 `nohup cmd &` 后断开连接，进程仍被 SIGHUP 带走；正确做法：`setsid nohup cmd > log 2>&1 < /dev/null & disown`，并确认 log 文件已生成。
- 现象/坑：本机 `python`/`py` 是 WindowsApps 0 字节别名；正确做法：一律全路径 `C:\ProgramData\anaconda3\python.exe` 或 `train\.venv\Scripts\python.exe`。
- 现象/坑：本机 12 GB 显存跑 27B 会连撞三堵墙（显存不足→bnb meta 张量崩→主机内存 OOM）；正确做法：不要在 12 GB 上再试 offload，直接上 24 GB 卡。
- 现象/坑：converter 在 Windows 上 `short source read`；原因：`os.open` 未加 `O_BINARY`（文本模式吃字节）+ 4 处 POSIX 调用缺失；正确做法：见 `CONVERTER-STATUS.md` §10 的 5 个补丁（云端 Linux 无需这些补丁）。
- 现象/坑：AutoDL 数据盘 150 G 很紧（base 52 + merged 54 + .ninfer 16 = 122 G）；正确做法：用 `dl_base_curl.py` 而非 huggingface_hub（后者会额外在 HF_HOME 存一份 52 G 缓存）；转换完成后删 `merged/`。
- 现象/坑：Qwen3_5 架构把 LoRA 挂到 `gdn.*` 会直接 NaN；正确做法：只挂 7 个 Linear（q/k/v/o/gate/up/down），脚本已写死。
- 现象/坑：写文件到 `D:\DrCE(26.2.16)\` 是禁止的（只读联动源）；正确做法：只在 `D:\BaiduNetdiskDownload\Local-AI\` 内写。

## 10. 关键文件与修改
- `train/kitty-rev/README.md`：数据四层构成与实况（3040 条数据集说明）。
- `train/kitty-rev/RUNBOOK.md`：数据构造→训练→回炉→验收全命令。
- `train/kitty-rev/REASONING-DATA.md`：开源推理链清单、实测保留率、无教师 key 的替代方案与混合结果。
- `train/kitty-rev/ENV-REPORT.md`：本机环境实测与缺口判定（3.12 非硬约束、cp313 wheel 存在）。
- `train/kitty-rev/docs-12gb-feasibility.md`：12 GB 跑 27B 的 8 条路径实测与结论。
- `train/kitty-rev/logs/`：ENV-STATUS / DOWNLOAD-STATUS / CONVERTER-STATUS / SMOKE-STATUS / HANDOFF / quality-*.
- `train/kitty-rev/data/{kb_re,kb_tools,seed_sft,seed_dpo,real_*,kb_*}.jsonl`：手写知识库、种子、真实轨迹。
- `train/kitty-rev/data/large{,-mix}/`：训练实际读取（3908 条）。
- `train/kitty-rev/scripts/`：extract_contracts.mjs / harvest_sessions.py / harvest_bulk.py / gen_kb.py / expand_dataset.py / expand_gold.py / run_expand.py / validate_dataset.py / train_kitty.py / mix_reasoning.py / fetch_reasoning.py / distill_cot.py。
- `train/kitty-rev/eval/eval_kitty.py`、`eval/eval_local.py`、`eval/bench/{manifest.json,fetch_bench.py,run_bench.py}`：验收体系。
- `train/tools/ninfer-master/`：转换器源码（Neroued/ninfer，含 5 处 Windows 补丁 + `.venv-convert`）。
- `train/tools/ninfer-convert/`：iamwavecut/ninfer-all 的 GGUF recipe 版转换器。
- `train/scripts/{merge.py,fetch_base.py,dl_base_27b.py,dl_base_curl.py}`：合并与下载工具。
- `train/kitty-rev/deploy/`：云部署包（`cloud/{setup,run_all,run_autodl}.sh`、`PROVIDERS.md`、`remote.py`、`kitty-rev-bundle-*.tar.gz`）。
- `docs/06-posttraining-feasibility.md`：已追加 §13 更正（converter 未丢失、不需要 GGUF）。
- `.gitignore`：已追加 kitty-rev 数据派生物排除。

## 11. 验证方式
- 环境：`python -c "import torch,transformers;print(torch.__version__,transformers.__version__)"` → 2.6.0+cu124 / ≥5.8。
- 数据：`validate_dataset.py --dir data/large-mix` → `VERDICT: PASS`。
- 训练：日志出现 `{'loss': ...}` 且逐段下降；`nvidia-smi` 显存 18–20 GiB。
- 回炉：`python -m tools.artifact.inspect <file>.ninfer` → 787 objects / 783 tensors。
- 部署：`curl 127.0.0.1:1234/v1/models` → 200 且出现新 name。
- 行为：`eval_kitty.py` 通过率 > 基线 13%。

## 12. 恢复指令
- 新对话打开本项目后执行 `/resume`，Agent 将读取本文件并从"§7 下一步"继续（先装 cusparselt → 验 torch → 起 smoke）。
