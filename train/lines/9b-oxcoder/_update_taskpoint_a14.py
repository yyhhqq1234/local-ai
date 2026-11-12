#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加 A14：基座切换为 SRA 版（操作者 2026-11-02 19:10 决定）"""
import io

P = "D:/BaiduNetdiskDownload/Local-AI/TASKPOINT.md"

A14 = '''
## A14. 基座切换为 SRA 版（2026-11-02 19:10 操作者决定）

### 决策

```text
基座：models/OxCoder-9B-sra-g1.0   （拒绝方向消融版，18.8 GB，分片权重）
放弃：models/OxCoder-9B            （原版，保留不动，6 轮历史训练都在它上面）
```

### SRA 版是什么（已实测确认，非推断）

| 项 | 值 |
|---|---|
| 改动方式 | 在第 6–24 层（共 19 层）的 `down_proj` / `o_proj` / `out_proj` 上减去一个方向向量 |
| 向量规格 | 每层 4096 维（= hidden_size），**范数 4.52 → 10.04 逐层增大**，19 层合计 420.17 |
| 移除能量 | 平均 **3.6%**（保留 96.4%） |
| 改动受控性 | **已逐张量验证**：非目标模块 6/6 抽样 maxΔ=0；层 0-5 与 25-31 的同样模块 maxΔ=0 |
| 附带文件 | `sra-directions.json`（10 KB，含每层 cos_dirty/cos_clean 证据）+ `sra-vectors.pt`（317 KB） |
| 权重完整性 | 760 个 tensor 键集与原版**完全一致**；总大小差 1624 字节（分片 padding） |

### 动态实测结论（2026-11-02 19:00，8 条 prompt 串行对比）

| 维度 | 结论 |
|---|---|
| 能力是否倒退 | ✅ **没有**：8 条全答，长度相当（code1 901→994 · code2 1698→1601 · rev 系列 ±5%） |
| code3（SQL） | ✅ SRA 更完整：原版 382 字符（篇幅花在编造工具上）→ SRA 1252 字符（直接给 SQL） |
| 去拒绝是否生效 | ⚠️ **无法证实**：原版本来就不拒这批请求，没有对照组 |
| 工具路由 | ❌ 中性偏负：kit1 从「编造 3 个」变「不给工具」；kit2 从「不给」变「编造 3 个」 |

### 同时发现的 base 固有问题（重要，记录备查）

```text
两个模型都会编造不存在的 kitty_* 工具名，尤其在不该调工具的场景：
  原版 code1  → kitty_create_file / kitty_write_file   （不存在）
  原版 code3  → kitty_sql                              （不存在）
  原版 kit1   → kitty_scan / kitty_static_analysis / kitty_unpacker_detect （不存在）
  SRA  kit2   → kitty_dbg / kitty_dis / kitty_mem       （不存在）

成因：system 里「你是 kitty 逆向工作台执行层，直接调用 kitty_* 工具」被过度执行，
     连「写个 Python 函数」都要套工具。
影响：这是 base 固有问题，**加数据修不好**（v5/v7 两轮已验证）
     它也解释了「Z-B 评测 40 条都是该调工具的场景，所以编造=0 能守住」，
     而编造实际发生在评测集只有 4 条的 N 类上。
```

### 训练计划（以 SRA 为基座）

| 项 | 设定 | 理由 |
|---|---|---|
| 基座 | `models/OxCoder-9B-sra-g1.0` | 本次决策 |
| 起点 adapter | **不使用 r3** | r3 是在原版上训的，套到消融版上可能冲突；且「去掉 r3」是至今未试的变量 |
| 数据 | `data/_legacy/mix-z-re-v4.jsonl` 7608 行 | 保持与 v4 可比 |
| 超参 | ctx 2048 · lr 2e-5 · ga 4 · bs 1 · seed 42 · LoRA r=32 α=64 | 同前 6 轮 |
| 步数 | 1902（7608/4） | 约 1.1 h |
| 产物 | `out/z-re-sra-v1` | — |
| 判据 | hit ≥ 36/40（acc ≥90%）· 编造 = 0 | 与 v4 同口径 |

### 变量说明（这次只动了一个变量）

```text
v4   = OxCoder-9B（原版）+ r3 + LoRA
sra1 = OxCoder-9B-sra-g1.0 + （无 r3）+ LoRA

变了两处：基座换成消融版、起点去掉 r3。
如果要更严格的单变量对比，可以再跑一版「原版 + 无 r3」。
```

'''

src = io.open(P, encoding="utf-8").read()
if "## A14." in src:
    print("[SKIP] A14 已存在")
else:
    marker = "\n## 1. 任务目标"
    i = src.find(marker)
    src = (src[:i] + A14 + src[i:]) if i > 0 else (src.rstrip() + "\n" + A14)
    io.open(P, "w", encoding="utf-8").write(src)
    print(f"[OK] A14 已插入（{A14.count(chr(10))} 行）")
print(f"[INFO] 文件 {len(src.split(chr(10)))} 行")
