# Local-AI · 本地大模型推理与后训练工作区

> 本仓库是操作者自建（SHIYI-WORKSPACE）的**本地模型工程**：把 Qwen3.8-27B（IQ2 量化）跑在单张 12G 笔记本显卡上，
> 接进 DeepSeek Harness（DSH）作为 provider，并围绕它做提示层瘦身、行为护栏、后训练数据整备。
>
> **仓库为私有（private）**：仅本人可见，不公开、不 fork、不转公开镜像。

---

## 1 项目定位

| 维度 | 内容 |
|---|---|
| 目标 | 在 12G 显存的笔记本上稳定运行 27B 级本地模型，并让它"像样地干活"（工具调用、长产物、收尾） |
| 硬件 | RTX 5070 Ti Laptop 12,227 MiB · 有效带宽实测 ≈ 675 GiB/s · 驱动 CUDA sm120 |
| 模型 | `Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer`（9.53 GiB，MTP head 已开） |
| 推理引擎 | NInfer（`ninfer-csunx`，v0.6.0，OpenAI 兼容 `/v1/chat/completions`） |
| 宿主 | DeepSeek Harness（DSH），通过自建插件 `plugins/dsh-ninfer-local` 接入 |
| 联动方 | `D:\DrCE(26.2.16)`（逆向工作台 kitty-toolbox）——**只读 + 复制，禁止写入** |

---

## 2 目录结构

```
Local-AI/
├── plugins/dsh-ninfer-local/     ★ 核心代码（入库）：DSH 的 ninfer provider 适配器
│   ├── lib/index.js              运行时产物（所有补丁落在这里）
│   ├── src/                      源码（与 lib 同步）
│   ├── PATCHES.md                逐轮改动记录（含"为什么没做"）
│   └── cordis.patch.yml          插件自装配补丁
├── train/                        后训练工作区（README 入库，权重与产物不入库）
│   ├── README.md                 磁盘预算与串行流程（27B 需串行删，峰值 162G）
│   ├── data/                     训练数据（train.jsonl / eval.jsonl）
│   └── scripts/                  setup_env / train_qlora / merge
├── _research/                    模型调研与选型备案（md 入库，hf 缓存不入库）
├── _work/session-audit/          会话审计脚本与解帧产物（脚本入库，大 jsonl 不入库）
│   ├── *.mjs                     解帧 / TTFT / 瘦身模拟 / 校验脚本
│   ├── KITTY-ISSUE-BACKLOG.md    kitty 适配问题的备案（供后训练）
│   └── ninfer-stats.jsonl        每请求 payload 统计（运行时产物，不入库）
├── _tools/                       探针脚本（ps1 / py / mjs）
├── ninfer-csunx/                 引擎运行时（2.7G，不入库）
├── ninfer-27b-kv-stream-3arch-*/ 模型权重（22G，不入库）
└── Local-AI-testarea/            本地模型测试产物（不入库）
```

---

## 3 快速开始

```powershell
# 1) 引擎（ninfer-csunx 内自带 run-engine.ps1）
cd D:\BaiduNetdiskDownload\Local-AI\ninfer-csunx
.\run-engine.ps1            # 监听 127.0.0.1:1234

# 2) 健康检查
curl http://127.0.0.1:1234/v1/models
# 期望：{"data":[{"id":"qwen3.8-27b-ablit-swift15-iq2s","meta":{"size":10241...,"n_params":28452653808}}]}

# 3) 插件已注入 DSH 后，在 GUI 选「NInfer 本地 · 5070Ti 12G」即可对话
#    验证裁剪是否生效：看每请求统计
Get-Content D:\BaiduNetdiskDownload\Local-AI\_work\session-audit\ninfer-stats.jsonl -Tail 3
# 期望：tools=16, effort=medium, payloadBytes≈4-7 万
```

---

## 4 核心组件：`dsh-ninfer-local`

一个 DSH 插件，把 NInfer 引擎接成 provider，并在适配器层做**只对本地模型生效**的优化与护栏。

### 4.1 当前配置（`lib/index.js` 的 DEFAULT_CONFIG）

| 键 | 值 | 作用 |
|---|---|---|
| `toolAllowlist` | 16 个工具 | 238 → 16，schema 264KB → ~26KB；含 `kitty_ce/kitty_ops/kitty_settings/kitty_status` |
| `stripToolHints` | `['js-reverse','jobs']` | 白名单里没有的工具，其说明段从 system 剔除（kitty 段按操作者要求保留） |
| `slimSkills` / `skillNameLimit` | true / 60 | `<available_skills>` 折叠为技能名（限 60 条），技能仍可 `skill` 工具加载 |
| `slimSystem` | true | 同名同内容的 markdown 段去重 |
| `executionRules` | 9 条 | 工具缺失上报 / 环境事实 / 验收纪律 / 规格核对 / 产物自检 / 临时文件 / 落盘勿回读 / kitty 收尾 type 语义 / 错误反应对照 |
| `offloadToolResultMaxChars` | 1200 | 大工具输出落盘 `_work/toolout/`，上下文只留头尾（`read/ops_grep` 等内容型工具不落盘） |
| `detectRepeatToolCalls` | true | 同结构调用 ≥3 或失败 ≥4 → 注入空转告警 |
| `stuckBreaker` | true | 同结构 ≥6 或失败 ≥6 → **finish=error 直接终止本轮**（stop 不会终止，实测 1044 步死循环） |
| `errorHints` | true | `ERR\|CODE` 自动追加"建议下一步"（6 类映射 + 兜底） |
| `sampling` | 4 档 | code 0.2 / creative 0.8 / fact 0.1 / default 0.6（含 top_p 与 presence_penalty） |
| `defaultEffort` / `effortCap` | minimal / medium | 尊重 ≤medium 的选择，high/xhigh/max 一律压到 medium |

### 4.2 性能基线（实测，冷启动）

| 指标 | 初始 | 当前 |
|---|---|---|
| system 字符 | 30,164 | 23,179～24,541 |
| 工具 schema | 238 个 / 264 KB | 16 个 / ~26 KB |
| 首字（冷） | 165～180 s | **13.9 s** |
| 首字（热） | — | 0.12 s |
| decode | — | 52～61 tok/s（带宽上限 70.8，已用 86%） |
| 前缀-速度关系 | — | ≤2K tokens 满速；6K 起衰减；30K 时 decode −28%、首字 41.6 s |

> decode 天花板 = 有效带宽 675 GiB/s ÷ 权重 9.53 GiB ≈ **70.8 tok/s**，单卡不换模型无法破 100。

### 4.3 已修的关键缺陷（详见 `PATCHES.md`）

1. **provider 归属**：ninfer 原先由 llm-pi-ai 的 PiAiAdapter 承载，自建适配器从未接真实流量 → 已切到 NinferAdapter
2. **回复被吞**：`block-end` 传空串，DSH 以 block-end.block 为最终内容 → 累积 textBuf/reasonBuf
3. **流非法**：`usage.reasoningTokens` 用 `|| undefined` → 只放有值字段
4. **skills 漏裁**：清单注入在 user 消息，旧逻辑只处理 system → 全消息折叠
5. **tool-call 整轮失败**：`tool-call-delta` 缺 index → 按 id 分配 + block index 顺延
6. **offload 递归**：落盘 → 模型 read 回 → 再落盘 → 内容型工具不落盘
7. **熔断失效**：`finish=stop` 不终止 DSH → 改 `finish=error(STUCK_LOOP)`

---

## 5 后训练

见 [`train/README.md`](train/README.md) 与 [`docs/03-posttraining.md`](docs/03-posttraining.md)。

数据来源：`_work/session-audit/` 下已解帧的会话日志（`s7`–`s11.jsonl`），含正负样本：

| 类别 | 样本 |
|---|---|
| 正向 | 正确工具链（write→read 验证）、正确 kitty 收尾（type=finish+evidence→task-close）、去审查测试 6/6 通过 |
| 负向 | 41 步空转（翻源码自造桥接）、16 步 wc -l 震荡、3000 字只给 1800、任务关闭后瞎试参数 |

后训练手段：QLoRA（4-bit）+ DPO；27B 需按串行顺序删中间件（峰值 162G）。

---

## 6 与 DrCE 逆向工作台联动

```text
D:\DrCE(26.2.16)  ← 只读源
  · 可以：读取源码/文档、复制文件到本仓库
  · 禁止：在该目录内创建/修改/删除任何文件（包括日志、缓存、临时文件）
  · 联动方式：复制 kitty-toolbox 的 schema/协议文档到本仓库 docs 或 _research 作为参考
```

联动的目的是：**用 DrCE 的真实工具契约，构造本地模型的后训练样本与提示约束**（如 kitty 的 12 种 taskTransition type）。

---

## 7 仓库约定

```text
可见性：private（仅本人）。不上公开镜像、不发 release、不接受外部 PR。
提交粒度：一次改动一个主题；涉及 lib/index.js 的补丁必须带 .bak-thinkN 备份说明。
不提交：模型权重、引擎运行时、训练中间件、日志、测试产物（见 .gitignore）。
```

---

## 8 文档索引

| 文档 | 内容 |
|---|---|
| [`docs/01-architecture.md`](docs/01-architecture.md) | 组件关系、数据流、端口与进程 |
| [`docs/02-local-model-adapter.md`](docs/02-local-model-adapter.md) | 适配器契约、chunk 类型、易踩坑点 |
| [`docs/03-posttraining.md`](docs/03-posttraining.md) | 后训练计划、数据格式、显存与磁盘预算 |
| [`docs/04-drce-linkage.md`](docs/04-drce-linkage.md) | 与 DrCE 的只读联动规范 |
| [`docs/05-optimization-log.md`](docs/05-optimization-log.md) | 30 轮优化纪实（含失败路径与原因） |
| [`docs/06-posttraining-feasibility.md`](docs/06-posttraining-feasibility.md) | 后训练可行性指南（能不能训 / 决策树 / 版本锁定 / 挂载红线） |
| [`plugins/dsh-ninfer-local/PATCHES.md`](plugins/dsh-ninfer-local/PATCHES.md) | 逐轮补丁清单与回滚点 |
| [`_work/session-audit/KITTY-ISSUE-BACKLOG.md`](_work/session-audit/KITTY-ISSUE-BACKLOG.md) | kitty 适配问题备案（后训练输入） |

---

## 9 环境事实（踩过的坑，写死在这里）

```text
· PATH 里的 python / python3 是 WindowsApps 的 0 字节别名，执行无输出 ≠ 没有 Python
  真实解释器：C:\ProgramData\anaconda3\python.exe（3.13.9），必须全路径调用
· py 启动器不存在；node 可用；shell 统一用 pwsh 全路径：
  & 'C:\Program Files (x86)\PowerShell\7\pwsh.exe' -NoLogo -NoProfile -Command '<cmd>'
· D 盘空间紧张（后训练前先看 Get-PSDrive D）
· 根目录在百度网盘同步目录内，出现过间歇性"文件不可见"，大批量操作前先确认
```
