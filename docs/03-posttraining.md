# 03 · 后训练计划

> 目录：`train/`｜既有说明：`train/README.md`（磁盘预算与串行流程）

## 1 目标

把本地模型在**工具使用与错误恢复**上的短板补进权重，减少对提示层约束的依赖。

当前靠提示/护栏兜住、但权重里没有的能力：

| 缺陷 | 现场证据 |
|---|---|
| 工具缺失仍硬做 | 41 步翻源码自造桥接（会话来 c4ea1e55 之前） |
| 收到明确错误指引仍穷举试参数 | 10 次 task-dispatch 变体（3197072f） |
| 目标达成不收手 | 模块数已拿到，仍折腾任务状态（3197072f / db680526 各残留 1-2 步） |
| 规格不达标即收工 | 要 3000 字给 1,800 |
| 反复自测 | health.sh 16 步 edit+wc -l、snake.py 9 步 |
| 单步思考过长 | medium 下仍见 7,285 字符 |

## 2 数据来源（已有）

| 文件 | 内容 |
|---|---|
| `_work/session-audit/s7.jsonl` | 42 条提示词包测试（去审查 6/6 通过、工具链 106 调用、鹈鹕落盘、推理陷阱 6 题） |
| `s8.jsonl` | kitty 32 步 abort（offload→read 递归） |
| `s9.jsonl` | kitty 22 步（task-dispatch 试错 10 次） |
| `s10.jsonl` | kitty 1044 步（熔断 finish=stop 死循环） |
| `s11.jsonl` | kitty **12 步 completed**（修复后基线） |
| `KITTY-ISSUE-BACKLOG.md` | 问题备案与后训练样本构造方向 |

解帧：`node _work/session-audit/unframe2.mjs <zstd> <out.jsonl>`

## 3 数据格式（计划）

```jsonl
// SFT（正样本：正确工具链 + 收尾）
{"messages":[{"role":"user","content":"..."},{"role":"assistant","content":"...","tool_calls":[...]}],"meta":{"session":"s11","steps":12,"outcome":"completed"}}

// DPO（同一 prompt 的 chosen / rejected）
{"prompt":"...","chosen":"先 task-dispatch{type:finish} 再 task-close","rejected":"换 10 种 taskTransition 反复试","meta":{"session":"s9","steps":22}}
```

构造要点：
```text
· 每条样本带 steps 与 outcome，便于按"步数超标"加权
· rejected 侧保留模型原话（含它自己的 reasoning），让 DPO 学到"这种推理会走向空转"
· 负样本优先取：步数 >15、abort、连续 ERR 且参数结构相同
```

## 4 训练方案

```text
基座：Qwen3.8-27B（或 8B 替代做快速验证）
方法：QLoRA 4-bit + DPO
显存：12G 笔记本只能跑 8B 级 QLoRA；27B 需换机或云端
磁盘：见 train/README.md —— 27B 串行峰值 162G，base/merged/gguf 三者任一时最多并存两个
```

## 5 验收标准

```text
1) kitty 任务：同一提示词 ≤10 步完成，且不触发熔断、无 abort
2) 规格达标：3000 字任务输出 ≥2800 汉字或主动续写
3) 错误恢复：收到 ERR|EARLY-EXIT-DENY 后第一次动作就正确（不再换参数）
4) 自测纪律：同一文件回读 ≤1 次
5) 步数分布：p90 ≤15 步（当前 p90 约 22）
```

## 6 与提示层的关系

```text
提示层（executionRules 9 条 + 错误建议 + 告警/熔断）是"外骨骼"，后训练是"内化"。
目标：训练后可以逐步撤掉外骨骼里的 3/4/9 条，行为仍然正确。
撤除顺序：先撤单条 → 跑同一组验收 → 通过再撤下一条；失败即回滚该条。
```
