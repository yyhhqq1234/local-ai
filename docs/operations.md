# 运维与联动

# 04 · 与 DrCE 逆向工作台联动（只读）

> 联动对象：`D:\DrCE(26.2.16)\`（kitty-toolbox 逆向工作台，独立 git 仓库）

## 1 边界（硬约束）

```text
允许：读取任意文件；把需要的文件复制到本仓库 docs/ 或 _research/ 后再引用
禁止：在 DrCE 目录内 创建 / 修改 / 删除 / 运行脚本 / git 操作 / 生成日志或缓存
原因：那是另一个项目的仓库，写入会污染它的 git 状态与运行产物
违反：视为未交付，需回滚并说明
```

自检命令（执行任何联动操作前）：
```powershell
# 确认没有意外写入：只看状态，不改
cd 'D:\DrCE(26.2.16)' ; git status --short
```

## 2 需要从 DrCE 取什么

| 需要的信息 | 位置（只读） | 用途 |
|---|---|---|
| kitty_settings 的 action 与 taskTransition 语义 | `kitty-toolbox/src/**` + 运行时 schema | 写进本地模型纪律（type 语义） |
| A 通道 OP 表 | `kitty-toolbox/src/bridge/**`、运行时 `kitty_ops` | 提示层速查 |
| 错误码定义（ERR\|XXX） | `kitty-toolbox/src/**` | adapter 的 `errorHints` 映射表 |
| 任务状态机（target-set → finish → close） | 同上 | 后训练样本的"正确路径"标注 |

## 3 联动工作流

```text
① 只读提取：在 DrCE 里读源码/文档，把片段复制到本仓库 _research/drce-refs/ 下
② 落成契约：把提取到的语义整理进 docs/02 或执行纪律，标注来源路径与版本
③ 构造样本：用真实错误码与真实状态机，改写成本地模型的 SFT/DPO 样本
④ 回归验证：跑同一组 kitty 任务，比较步数与错误次数
```

## 4 已知契约要点（截至 2026-10-20，来自 DrCE 运行时 schema）

```text
taskTransition 必带 type（不是 state），12 种：
  enter-task{sessionGoal,targetProcess,targetKind} | enter-standby | stage-start{stage}
  | stage-complete{stage,evidence?} | stage-fail{stage} | retry-stage{stage}
  | block{stage,question} | answer{questionId,answer} | complete{evidence[]非空}
  | finish{evidence[]非空} | abandon{reason?} | set-consent{consent}

收口顺序（推荐一步）：task-dispatch{"type":"finish","evidence":[...]} → task-close
task-close 不接 transition、不接 generation
EARLY-EXIT-DENY        = terminalState 仍为 none，需 finish / abandon / enter-standby 解锁
TASK-TRANSITION-UNKNOWN = type 写错（把 state 当字段就是错）
```

## 5 与本仓库的关系

```text
DrCE 是"工具真实契约"的来源；本仓库是"模型侧适配与训练"的场所。
两者不合并、不同步 git，只通过"复制出来的参考文件"发生联系。
```

## 6 记录要求

每次从 DrCE 取内容，在本文件追加一行：
```text
2026-10-20 | kitty_settings.taskTransition 的 12 种 type | 来源：DrCE 运行时 schema（kitty_settings.description）
```


---

## 附 · 引擎切档（2026-11-12 新增）

```powershell
# 查看当前谁在跑
python engines/switch-model.py status

# 9B（llama.cpp）三档
python engines/switch-model.py 9b fast    # 8k ctx，decode 70–75
python engines/switch-model.py 9b 128k    # 128k ctx，decode 44
python engines/switch-model.py 9b 256k    # 256k ctx（KV 在主机内存），decode 20

# 27B（NInfer）
python engines/switch-model.py 27b

# 全停
python engines/switch-model.py stop
```

互斥原因：9B 权重 6.19 GB + 27B 权重 9.55 GB > 本机 12 GB 显存，两个引擎不能同时驻留，
因此共用 8080 端口，谁起谁占。
