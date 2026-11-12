#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 A12（2026-11-02 本轮进度与计划更新）插入 TASKPOINT.md 的 A 段末尾（A11 之后）"""
import io, os

P = "D:/BaiduNetdiskDownload/Local-AI/TASKPOINT.md"

A12 = '''
## A12. 本轮进度与计划更新（2026-11-02 15:00）

### 目标升级（操作者 11-02 下达，高于 A11 的封板标准）

| 腿 | A11 封板标准 | **本轮目标** | 差距 |
|---|---|---|---|
| Z-B（kitty 工具选择） | hit 30/40 · acc 75% | **acc ≥90%（hit ≥36/40）· 编造 0** | 差 6 条 |
| 2B（NSFW 门控） | GateLeak ≤5% | **recall ≥0.90 · leak ≤0.05 · FPR ≤0.05 · trap ≤0.10** | FPR 超 7.5 倍 · trap 超 10 倍 |

手段约束：**优先靠训练达成，不靠 system 索引 / 外部路由层等外挂**。

### 进度对照（A5 的 1-8 步全部完成，本轮在 A7 的 5.3 段上迭代）

| 阶段 | 状态 | 实例 |
|---|---|---|
| A5 步骤 1-8（方案 Z 双 PASS） | ✅ 完成 | `z-re-v4` / `z-2a-v7` |
| **5.3 段：2B 门控** | 🔄 **迭代中（4 轮）** | v1 FPR 1.0 → v2 FPR 0.375 → v4 已训完（**发现泄漏，作废**）→ **v4b 待训** |
| **Z-B 提准（新增，A11 无此阶段）** | 🔄 **迭代中（4 轮）** | v4 30/40 → v5 29/40 → v6 待训 → **v7 待训（+456 条直接答）** |
| 5.4 段：2C 长上下文 | ⏸ 未开始 | 押后 |
| P3：merge + 冒烟 | ⏸ 未开始 | 押后 |

### 本轮新增的 6 条雷区（必须写入 A8）

```text
① 训练集抄评测集原文 → 泄漏
   实测：2B v4 的 normal 桶直接用了 val/nsfw-gate.jsonl 的 20 条原文，
        9 条 trap 全部命中 → v4 的 final 在 trap 上的分数完全不可信
   正确做法：生成训练数据后用「评测集 user 全量比对」做泄漏复检，必须为 0

② 纪律样本写死「一次只给一个工具」→ 压死多步任务
   实测：v5 加这条纪律后 G11（需 net+proto 两工具）从对变错，L3 净退 3 条
   正确做法：纪律要写成「先给最该做的那一个；需要串联时按依赖顺序给出，每步带判据」

③ 正例问法拿工具 description 当问句 → 教成「介绍工具」而非「用工具」
   实测：v5 的 G33 期望调 kitty_asm，模型改给纯文字讲解，got=[]
   正确做法：问句用任务式「用工具完成 X，给出调用」

④ 训练集 meta 字段结构不一致 → datasets 加载直接失败
   实测：同一文件里 meta 有 4 种结构，抛
        TypeError: Couldn't cast array of type struct<...> to {...}
   正确做法：训练数据只留 messages，用 _sanitize_for_train.py 净化；
            用 _validate_train_data.py 真实调 load_dataset 验证（--dry-run 验证不到）

⑤ git-bash 没有 flock 命令
   实测：脚本里 if ! flock -n 9 永远为真 → 误报「锁被占」直接退出
   正确做法：Windows 用 pidfile + kill -0

⑥ 长任务无实例锁 → 双实例抢 12G 显存
   实测：Z-B v6 同秒启动两个进程，2B v4 在 6552/8043 被挤死、v6 掉到 186 s/it
   正确做法：所有训练链带 pidfile 锁；第二条链用等待式（轮询前一条 pid）
```

### 计划需要更新的 4 处

```text
1. A5 增加第 9 步「达标迭代」：对 Z-B 和 2B 各做 N 轮数据修复→重训→评测，直到命中判据
2. A7 的 5.3 段拆成 5.3a（结构修复迭代）与 5.3b（最终验收），因为一次训练达不到
3. A8 增补上面 6 条雷区
4. 新增固定环节（原计划没有）：
   · 评测集审计（_audit_evalsets.py）：卫生 / 分布 / 泄漏三项
   · 训练覆盖率分析（_predict_v6.py）：判断「补相似表述」是否有效
   · 数据泄漏复检：训练集 user 与评测集 user 全量比对
```

### 本轮已完成的具体产物

| 类型 | 文件 |
|---|---|
| 数据（Z-B） | `mix-z-re-v7-train.jsonl` 10636 行（v6 mix + 456 条直接答样本） |
| 数据（2B） | `train-2b-gated-v4b-train.jsonl` 32174 行（28 题全换，泄漏 0，比例 1:1.11） |
| 审计工具 | `_audit_evalsets.py` · `_predict_v6.py` · `_sanitize_for_train.py` · `_validate_train_data.py` |
| 已训成品 | `2b-nsfw-v4/final`（**分数不可信，受泄漏影响**）· `z-re-v6` 未训 |
| 事故记录 | 双实例抢显存 · flock 不存在 · meta schema 不一致 |

### 下一步（等操作者指令）

```text
① 训 Z-B v7（10636 行 / 2659 步 / 约 1.6 h）→ 判据 hit ≥36/40
② 训 2B v4b（32174 行 / 8044 步 / 约 7.5 h）→ 判据 FPR ≤0.05 · trap ≤0.10
③ 两条都出数后，再判断是否进入 2C / P3
```

'''

src = io.open(P, encoding="utf-8").read()
marker = "\n## 1. 任务目标"
if "## A12. 本轮进度与计划更新" in src:
    print("[SKIP] A12 已存在")
else:
    i = src.find(marker)
    if i < 0:
        src = src.rstrip() + "\n" + A12
    else:
        src = src[:i] + A12 + src[i:]
    io.open(P, "w", encoding="utf-8").write(src)
    print(f"[OK] A12 已插入（{A12.count(chr(10))} 行）")
print(f"[INFO] 文件现 {len(src.split(chr(10)))} 行")
