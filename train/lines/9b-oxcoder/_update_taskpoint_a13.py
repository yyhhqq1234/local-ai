#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""追加 A13：以 z-re-v4 为基础 + 清理记录"""
import io

P = "D:/BaiduNetdiskDownload/Local-AI/TASKPOINT.md"

A13 = '''
## A13. 基准定档与清理（2026-11-02 17:30）

### 决策：以 z-re-v4 为基础，r3 保留

操作者指令原文：「接下来还是以 z-re-v4 为基础（r3 也保留下来），然后清理其他的内容」

| 角色 | 路径 | 成绩 | 说明 |
|---|---|---|---|
| **kitty 腿基准** | `out/z-re-v4/final` | 30/40 · 75.0% · 编造 0 · 选错 6 · 参数错 4 | 后续所有改动以它为对照 |
| **基线保留** | `out/re-stage1-r3/final` | 30/40 · 75.0% · 选错 7 · 参数错 3 | 操作者要求保留 |
| 编码腿成品 | `out/z-2a-v7/final` | cov 0.6462 · code 0.625 · tool_call 0 | PASS，保留 |
| 门控对照 | `out/2b-nsfw-v2/final` | FPR 0.375 · trap 1.00 · recall 0.8333 · leak 0 | FAIL，但作 v4b 的对照基线 |

### 清理明细（释放 29 GB · 磁盘 78 GB → 107 GB）

| 清理对象 | 体积 | 理由 |
|---|---|---|
| `out/2b-nsfw/` | 4.3 GB | v1 · FPR 1.0，最差 |
| `out/2b-nsfw-v4/` | 6.9 GB | 数据含 20 条评测集原文泄漏 → 作废 |
| `out/z-re-v7/` | 4.9 GB | 29/40，不如 v4；权重还是 fp32（331 MB） |
| `out/z-re-v5/` | 3.3 GB | 29/40，不如 v4 |
| `out/mix-v5/` `out/mix-v8/` | 372 MB | 单 adapter 混合方案，两次实证 tool_call 泄漏 42.5-47.5% |
| `out/z-re-v6/` | 1 MB | 空目录（未训） |
| `2b-nsfw-v2` 的 8 个 checkpoint | 8.1 GB | 保留 final 即可 |
| `z-2a-v7` 的 4 个 checkpoint | 2.1 GB | 保留 final 即可 |
| `data/_legacy/mix-z-re-v5/v6/v7*.jsonl` | 约 50 MB | 对应产物已删 |

保护项全部未动（models / 27b-kittyrev / .venv / ninfer-* / plugins / _work/session-audit）。

### 四轮迭代的完整成绩（作为后续对照）

| 版本 | hit | acc | 选错 | 参数错 | 关键改动 | 净值 |
|---|---|---|---|---|---|---|
| r3 | 30 | 75.0% | 7 | 3 | 基线 | — |
| **v4** | **30** | **75.0%** | **6** | **4** | mix 7608 行 | 与 r3 持平（选错-1、参数错+1） |
| v5 | 29 | 72.5% | 5 | 4 | +318 条对比样本 | -1 |
| v7 | 29 | 72.5% | 7 | 4 | +456 条直接答 + 多步链 | -1 |
| v6 | — | — | — | — | 未训（数据已随清理删除） | — |

结论：**加数据这条路已走到头**。v5/v7 各加 8%-22% 新样本，净值都是负的。
30/40 是「r3 起点 + 7608 行」这个组合的天花板。

### 后续方向（9B 线内，不跨 27B）

```text
A 精准替换（优先）  不改总行数 7608，只把 6 组混淆工具的低质表述
                   换成场景化表述 → 预期 32-34/40 → 1.5 h
B 换起点重训        不用 r3，从 Qwen3.5-9B 直接训，数据扩到 3-5 万行
                   （只能用 9B 自己现有语料）→ 8-12 h
C 两阶段 curriculum v4 基础上只训错例 → 再全量微调 → 3 h
D 接受 75%          v4 即 9B + 12G 卡的工程上限
```

### 已否决的路径（不要重提）

```text
✗ 用 27B 的 kittyrev 产物生成数据蒸馏给 9B —— 违反 §3.1 双线隔离（9B/27B 不得互相影响）
✗ 继续无脑加训练数据 —— v5/v7 两次实证净值为负
✗ 单 adapter 混合 —— mix-v5/v8 两次实证 tool_call 泄漏 42.5-47.5%
```

'''

src = io.open(P, encoding="utf-8").read()
if "## A13." in src:
    print("[SKIP] A13 已存在")
else:
    marker = "\n## 1. 任务目标"
    i = src.find(marker)
    src = (src[:i] + A13 + src[i:]) if i > 0 else (src.rstrip() + "\n" + A13)
    io.open(P, "w", encoding="utf-8").write(src)
    print("[OK] A13 已插入")
print(f"[INFO] 文件 {len(src.split(chr(10)))} 行")
