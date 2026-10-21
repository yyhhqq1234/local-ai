# kitty-rev · 逆向工作台能力后训练数据与训练包

> 目标模型：`Huihui-Qwen3.8-27B-abliterated-Swift-1.5-GSQ-RCO-IQ2_S-mtp.ninfer`（部署中）
> 目标：把 **kitty 逆向工作台的操作纪律 + 专业逆向知识 + 专业工具用法** 训进权重。
> 训练命令见 [`RUNBOOK.md`](RUNBOOK.md)；可行性红线见 [`../../docs/06-posttraining-feasibility.md`](../../docs/06-posttraining-feasibility.md)。
> **当前状态：数据层已就绪并通过质检（3040 条 / 48 偏好对）；训练未开跑（引擎由操作者停止）。**

---

## 1 四层数据（为什么这么分）

| 层 | 内容 | 来源 | 条数 | 治什么病 |
|---|---|---|---|---|
| **契约层** | 64 工具 / 66 OP / 12 transition / 28 错误码的签名·回包·坑·路由 | 只读抽取 `D:\DrCE(26.2.16)\kitty-toolbox\src\*.ts` | 银层为主 | 猜工具名、猜 OP 参数、`state`/`type` 混淆 |
| **知识层** | 逆向专业知识 55 条（PE/x64/定位/内存/扫描/调试/脱壳/.NET/Unity/UE/APK/协议/补丁/对抗/纪律） | 手写 `data/kb_re.jsonl` | 220（gold） | 「会用工具但讲不清判据」 |
| **工具层** | 61 条 / 35 款专业软件用法（IDA/Ghidra/x64dbg/WinDbg/CE/r2/BN/DIE/PE-bear/System Informer/Procmon/API Monitor/Scylla/UPX/YARA/tshark/mitmproxy/Frida/objection/jadx/apktool/de4dot/dnSpy/Il2CppDumper/Cpp2IL/AssetRipper/FModel/UE4SS/UEDumper/capstone/angr/LIEF/pwntools/工具链组合） | 手写 `data/kb_tools.jsonl` | 244（gold） | 「只会 kitty，不会独立工具链」 |
| **轨迹层** | 真实会话轨迹 + 多轮任务轨迹 + 逐步决策 + 错误恢复 | `~/.dsh/sessions` 469 份解帧 + `_work/session-audit/s*.jsonl` + 手写场景 | 501（gold） | 空转、不收敛、不收口、动作不像人 |

护栏样本：`guard`（错误打算 → 正确动作）96 + `kb-guard`（知识误判纠正 23 主题）46。

---

## 2 当前数据实况（`data/large/manifest.json`）

```text
SFT 总量      3040   train 2736 / eval 304（按 prompt 前 40 字分组切分，防泄漏）
DPO 偏好对     48    chosen=正确动作序列，rejected=真实事故原话或常见误判
分层          silver 2196 · gold 702 · guard 142
契约覆盖      tools 64/64 · ops 66/66 · transitions 12/12 · 错误恢复 19 类
token 分布    avg 257 / max 1500（ctx 2048，零超限）
丢弃          448 条（压缩后仍超 1500 token 的真实轨迹，宁缺不糊）
质检          struct 0 · dup 0 · contract 0 · tool_call 0 · over_ctx 0 · 污染 0 → PASS
```

类别分布（train）：

| 类别 | 条数 | 说明 |
|---|---|---|
| tool-action | 529 | 195 个 tool×action 的用途/参数/失败判据 |
| op-syntax | 473 | 66 条 OP 的签名/回包/坑，多问法 |
| real-discipline | 383 | 真实会话里的工具纪律（跨 9 个项目） |
| tool-route | 292 | 64 工具的分工与替代 |
| kb-tool | 221 | 专业软件用法（35 款） |
| kb-re | 194 | 逆向原理与判据（15 主题） |
| action-reverse | 165 | 「这个 action 属于哪个工具」反向路由 |
| trajectory | 100 | 多轮任务轨迹（19 场景 × 问法变体） |
| guard / kb-guard | 96 / 46 | 反例纠正 |
| transition-syntax | 60 | 12 个 transition 的最小 JSON + 常见错法 |
| error-recovery | 51 | `ERR|`码 → 唯一正确下一步 |
| real-kitty | 118 | kitty 真实成功轨迹（DrCE 为主） |
| next-action / op-tool-map / error-trajectory | 36 / 35 / 6 | 逐步决策、OP↔工具映射、错误注入恢复 |

---

## 3 目录

```text
train/kitty-rev/
├── README.md                   本文件
├── RUNBOOK.md                  可执行命令全集
├── contracts/                  只读抽取的真实契约（可重抽）
│   └── tools.json  ops.json  transitions.json
├── data/
│   ├── kb_re.jsonl  kb_tools.jsonl      ★ 手写知识库（改这里 → 重跑 gen_kb.py）
│   ├── seed_sft.jsonl  seed_dpo.jsonl   手写行为种子
│   ├── real_sft.jsonl                   真实轨迹（session-audit 精确解帧）
│   ├── real_kitty.jsonl  real_disc.jsonl 真实轨迹（~/.dsh/sessions 批量解帧）
│   ├── kb_sft.jsonl  kb_dpo.jsonl       知识库扩产结果
│   └── large/{train,eval,dpo}.jsonl + manifest.json   ★ 训练实际读取
├── scripts/
│   ├── extract_contracts.mjs   契约抽取（只读 DrCE，零写入）
│   ├── harvest_sessions.py     session-audit 精确解帧
│   ├── harvest_bulk.py         ~/.dsh/sessions 批量解帧（kitty 优先 / 纪律类）
│   ├── gen_kb.py               知识库 → 多形态问答（含 23 条误判纠正 + DPO）
│   ├── expand_dataset.py       契约模板（OP 语法 / 工具路由 / transition / 错误码）
│   ├── expand_gold.py          gold 层（多轮轨迹 / 逐步决策 / 错误注入 / DPO 配对）
│   ├── run_expand.py           统筹生成 → data/large/（含裁剪与分组切分）
│   ├── validate_dataset.py     质检门（不过不训）
│   ├── train_kitty.py          QLoRA SFT + 可选 DPO（LoRA 红线写死）
│   └── fix_jsonl_quotes.py     JSONL 裸引号修复工具
├── eval/eval_kitty.py          行为判据集（逐类别过/不过）
└── logs/                       质检报告与验收报告
```

---

## 4 重建一条命令

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev
node scripts\extract_contracts.mjs
& "C:\ProgramData\anaconda3\python.exe" scripts\harvest_sessions.py
& "C:\ProgramData\anaconda3\python.exe" scripts\harvest_bulk.py --prefix real_kitty
& "C:\ProgramData\anaconda3\python.exe" scripts\harvest_bulk.py --require any --max-steps 20 --prefix real_disc
& "C:\ProgramData\anaconda3\python.exe" scripts\gen_kb.py
& "C:\ProgramData\anaconda3\python.exe" scripts\run_expand.py --variants 8
& "C:\ProgramData\anaconda3\python.exe" scripts\validate_dataset.py --dir data\large --ctx 2048 --md logs\quality-latest.md
```

判据：契约 64/66/12/28；`sft_total` 与 `[shrink] kept` 一致；质检 `VERDICT: PASS`。

---

## 5 数据纪律（违反即返工）

```text
1 契约只从 kitty-toolbox 只读抽取，不手抄工具名；DrCE 目录零写入
2 知识库只写「有判据的事实」，每条带 kitty 落地映射或明说没有封装
3 真实轨迹只取 completed 且以 assistant 文本结尾的轮次；ERR 占比 >50% 的轮次丢弃
4 超长轨迹先裁工具回包，再裁中间 assistant，仍超 1500 token 就丢弃（宁缺不糊）
5 eval 按 prompt 前 40 字分组切分，同 prompt 不跨侧（防泄漏）
6 每次改动后必须重跑 validate_dataset.py，PASS 才允许进训练
```

---

## 6 下一步（数据侧）

```text
1 知识层扩产：现 116 条 / 35 款工具。优先补 WinDbg 内核调试、ETW/回调、驱动逆向、固件/UEFI、
  Go/Rust 二进制、JS/Electron 逆向、UE5 与 Unity 6 差异、TLS 抓包与 pinning 对抗
2 轨迹层扩产：新会话产生后重跑 harvest_bulk 即增量；目标累计 ≥2000 条真实轨迹
3 DPO 扩产：把 real_*_neg 的真实失败轨迹按场景配对，目标 ≥100 对
4 验收：引擎重启后跑 eval_kitty.py 出「训练前/训练后」对比（基线已存档 logs/eval-baseline-20261020.json，3/23 = 13%）
```
