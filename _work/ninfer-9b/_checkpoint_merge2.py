"""TASKPOINT 增量更新 #2（保留全部旧内容，追加 ⑤ 专项 13 层与定论）。"""
import re
from pathlib import Path

p = Path(r"D:\BaiduNetdiskDownload\Local-AI\TASKPOINT.md")
src = p.read_text(encoding="utf-8")
before = len(src)

HEADER_NEW = """# TASKPOINT — 项目级任务断点

> 保存时间：**2026-11-08 22:00（UTC+8）**
> 项目根目录：D:\\BaiduNetdiskDownload\\Local-AI
> 分支/版本：main @ af914b6（工作区另有大量未提交改动；训练产物与引擎运行时均在 .gitignore 内）
> 本次性质：**①③④② 完成并可用；⑤ 投机链路已打通（13 层修复）但 MTP 接受率≈0，34.4 tok/s 为当前权重天花板**
> 历史归档：旧版 2622 行（A1–A27 + §1–§26）压缩至 §13；原文见 `git log -- TASKPOINT.md`。

---
"""

READ_FIRST = """## ▶ 接手先读这一段

```text
目标：让 ninfer-serve.exe（Windows 原生）把后训练 Oxcoder9B 跑成可交付推理服务（五项验收）。

已完成（全部实测）
  ① 5 prompt × 3 轮 = 15/15（内容非空）· 长 prompt 312 token 3/3 · 失败只死单请求
  ② --vision 启动 7.1 s；HTTP URL 图片 → decode→image token→vision tower→文本，可复现
  ③ 普通对话（含长 prompt）正常；带 tools 内容退化属"可后续"
  ④ 冷启 7.1 s、长 prompt TTFT 225 ms、前缀复用命中更快
未完成
  ⑤ 34.4 tok/s（无投机）。投机链路已打通（--spec mtp --draft-tokens 1 → 31.4 tok/s），
    但 --request-log-jsonl 实测 decode.rounds=191 生成 192 token
    ⇒ MTP 的 draft 接受率 ≈ 0，投机无收益。需用 G1 量化后的 text 权重重训 MTP 头才有望突破。

交付物
  out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer（7.93 GB / 738 objects / text+vision+mtp / G1=q8 gate·up）
  启动：& _tools\\run-serve.ps1            → ①③④
        追加 --vision                      → ②
        --spec mtp 可用但不建议（31.4 tok/s，负收益）

下一动作：⑤ 若要继续 —— 用 G1 量化后的 text 权重重新训练 MTP 头（对齐量化后 hidden 分布），
          或换 dflash/dflash2 投产权重（本地无）；否则 34.4 tok/s 是本机 12 GB 卡的交付上限。
```

---
"""

DONE_ADD = """
### 6.10 ⑤ 投机链路专项（2026-11-08 21:00–22:00）—— 连破 13 层并首次跑通

- [x] **pair 的 k=4096**：`pair/q8/shapes/n1024_k5120.cu` 加 `select_q8_pair_n1024_k4096`（实现本就参数化，转发即可）。
- [x] **mtp attention 的 contiguous parent**：转换器 group 必须把 `query+gate+key+value` **四合一**（10240 行）
      成同一 parent，且四者 format/layout/method 全同（`qwen3_5.py` 的 mtp block）。
      验证：`[wv-parts]` 打印从「4 个不同 parent」变为「同 parent 且行区间连续」。
- [x] **q8 两个形状**：`projection/q8` 加 `(10240,4096)`、`(4096,4096)`（K 相同转发）。
- [x] **bf16 一个形状**：`projection/bf16` 加 `(24576,4096)`（转发 n12288_k4096）。
- [x] **fold 的 GDN 层数**：`fold_io.cuh` 加 `FoldGeometry24x32 = FoldGeometry<24,16,32,8192>`，
      `launch.h` 判定 `spec.layers == 24`，`fold.cu` 加对应 case。
      **关键认知：fold spec 的 layers 是 GDN 层数（32 层里每 4 层 1 个 full-attn → 24），不是总层数。**
- [x] **slice 三处运行期化**：`split/.../n4096_n12288_k5120/small.cu:232`、`input_conv/q4_q5/projection.cpp:18`、
      `input_conv/q4_q5/projection_mma.cu:39` 的 `6144` 全部改为按张量实际行数/权重推导。
- [x] **Q5 direct SIMT static K**：`convolution.cu:173`、`projection_independent.cu:117 / 170`（T=4 verify 路径）
      按 `x.ne[0]` 分派 4096/5120 两套 schedule 实例。
- [x] **split_bf16_features 几何**：`indexing/features.cu` 的 14336 / 256×24 / 256×4 硬编码改为
      从输出张量推导（`hd*(2q+2k)`），27B 与 9B 通用。
- [x] **投机首次跑通**：`--spec mtp --draft-tokens 1/3` 均可完整生成 192 token，无崩溃、无 500。
      实测：draft=1 → 31.4 tok/s；draft=2 → 13.4；draft=3 → 10.4–16.4（均低于无投机 34.4）。
- [x] **接受率取证**：`--request-log-jsonl` 显示 `decode.rounds = 191`、产出 192 token
      ⇒ 每轮仅 1.0 token ⇒ **MTP draft 接受率 ≈ 0**（draft=1 时若接受应约 96 轮）。
"""

NEXT_NEW = """## 7. 进行中 / 下一步（新对话先干这个）

### 7.1 ⑤ 的定论（已取证，不是调度问题）

```text
实测：--spec mtp --draft-tokens 1，192 token 请求
  tps = 31.4
  decode.rounds = 191        ← 191 轮只产出 192 token
  decode.device_wait_exposed_seconds = 6.05
判读：draft=1 每轮 verify 2 列（target 1 + draft 1）
      若 draft 被接受则该轮出 2 token → 192 token 只需约 96 轮
      实际 191 轮 ⇒ **每个 draft 都被拒，接受率 ≈ 0**
⇒ 每轮白付一次 MTP forward + fold + 2 列 verify，故比无投机更慢。
```

**成因（按概率）**：MTP 头与 G1 量化后的 target 分布不对齐 —— 具体可能是
① MTP 训练时的 target 未做 G1（gate/up 升 q8），分布偏移；
② MTP 的 hidden 输入绑定到错误的层/位置（`mtp/pre_fc_norm_hidden`）；
③ MTP 与 text 权重不是同一来源世代。

### 7.2 下一步动作（三选一，按成本）

```text
A（最彻底）用 G1 量化后的 text 权重重训 MTP 头 → 对齐后接受率才有意义
B（验证成因）对比 MTP 的 hidden 输入：dump `mtp/pre_fc_norm_hidden` 的 l2，
   与 text 最后一层 final hidden 对比，看是否取错层/错位置
C（放弃投机）确认 34.4 tok/s 为交付上限，把 ⑤ 记为"受权重与硬件限制"
```

### 7.3 待验证假设

- 假设 1：若能拿到 dflash/dflash2 投产权重（本地无），可绕过 MTP 对齐问题。
- 假设 2：34.4 tok/s 已接近 12 GB 卡的带宽上限（5.81 GiB/token × 34.4 ≈ 200 GB/s，峰值 23-26%），
  非投机路径的优化空间有限（⑤-A 的 GEMV kernel 已实测无效）。
"""

LEI_ADD = """
### 9.9 ⑤ 专项新增雷区（2026-11-08 21:00–22:00，只增不减）

- 现象/坑：改 `.h` / `.cuh` 后行为不变、报错照旧；原因：Ninja 不跟踪头文件；
  正确做法：改头文件后手删依赖 `.obj`（本轮 `gdn/replay/launch.h` 需删 gdn/replay 全部 obj）。
- 现象/坑：`cudaErrorIllegalAddress` 只告诉你"越界"，不给 kernel 名；
  正确做法：`compute-sanitizer --tool memcheck --launch-timeout 300 --target-processes all <exe> <args>`，
  它会打印 `Device Frame: <kernel<模板参数>>(…) +0x… in <文件>:<行>` —— 本轮据此定位到
  `recurrent_fold_kernel<FoldGeometry<30,16,32,8192>> at fold_io.cuh:179`。
- 现象/坑：fold 的 `spec.layers` 是 **GDN 层数**（32 层里 24 个 linear-attention 层），不是总层数；
  误用 30/32 层实例会在 `recurrent_fold_kernel` 里越界读写 state slot。
- 现象/坑：引擎报 `q8 linear: unsupported shape` / `bf16 linear: unsupported shape` 不说是哪个形状；
  正确做法：在 `projection/q8/q8_dispatch.cpp`、`projection/bf16/bf16_dispatch.cpp`、
  `core/tensor.cpp`（slice）、`gdn/replay/launch.h`（fold）的抛错前加 `fprintf`，一层一层剥。
  **定位完必须删掉这些打印。**
- 现象/坑：PowerShell 单引号字符串里的 `` `r`n `` 不展开，写进源码会变成字面反引号字符导致编译失败；
  正确做法：用双引号字符串或 `[Environment]::NewLine`。
- 现象/坑：`"run$n:"` 报「变量引用无效」；正确做法：`"run${n}:"`。
- 现象/坑：`--prefill-chunk 40` 之类小值会让引擎打印 usage 直接退出；可用值是 128（实测）。
- 现象/坑：`--request-log-jsonl` 的 `argv` 行会很长，`Select-String` 过滤时注意截断。
"""

HIST_ADD = """- 2026-11-08 22:00：**⑤ 投机链路打通并定性** —— 连破 13 层（pair k4096 / mtp attention 四合一 /
  q8 两形状 / bf16 一形状 / fold 24 层 GDN 几何 / slice 三处 / Q5 static K 三处 / split_bf16_features 几何），
  `--spec mtp` 可完整生成 192 token；但 `decode.rounds=191` 证明 MTP 接受率≈0，
  投机为负收益（31.4 vs 无投机 34.4）。结论：34.4 tok/s 是当前权重的天花板，
  突破需重训 MTP 头或换 dflash 权重。①③④② 全部完成并可用。
"""


def replace_block(text, start, end, new_block):
    i = text.find(start)
    j = text.find(end, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return text, False
    return text[:i] + new_block + text[j:], True


m = re.match(r"^# TASKPOINT.*?\n---\n", src, re.S)
if m:
    src = HEADER_NEW + src[m.end():]
    print("header: ok")

src, ok = replace_block(src, "## ▶ 接手先读这一段", "## 1. 任务目标", READ_FIRST)
print("read_first:", ok)

i = src.find("## 7. 进行中")
if i > 0:
    src = src[:i] + DONE_ADD.lstrip("\n") + "\n" + src[i:]
    print("done_add: ok")

src, ok = replace_block(src, "## 7. 进行中", "## 8. 待办步骤", NEXT_NEW)
print("next:", ok)

i = src.find("## 10. 关键文件与修改")
if i > 0:
    src = src[:i] + LEI_ADD.lstrip("\n") + "\n" + src[i:]
    print("lei_add: ok")

if "### 13.4 更新历史" in src:
    src = src.rstrip() + "\n" + HIST_ADD
    print("hist_add: ok")

p.write_text(src, encoding="utf-8")
print(f"written: {before} -> {len(src)} chars")
