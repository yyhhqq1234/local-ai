"""TASKPOINT 增量更新（保留旧版全部内容，按标题锚点插入/替换本次会话增量）。"""
import io
import re
import sys
from pathlib import Path

p = Path(r"D:\BaiduNetdiskDownload\Local-AI\TASKPOINT.md")
src = p.read_text(encoding="utf-8")
orig_len = len(src)

HEADER_NEW = """# TASKPOINT — 项目级任务断点

> 保存时间：**2026-11-08 20:30（UTC+8）**
> 项目根目录：D:\\BaiduNetdiskDownload\\Local-AI
> 分支/版本：main @ af914b6（工作区另有大量未提交改动；训练产物与引擎运行时均在 .gitignore 内）
> 本次性质：**9B 交付形态已成立（①③④ 完成、② 视觉链路通），⑤ 投机链路连破 7 层、剩 GDN conv 的 27B 常量**
> 历史归档：旧版 2622 行（A1–A27 + §1–§26）压缩至 §13；原文见 `git log -- TASKPOINT.md`。

---
"""

READ_FIRST = """## ▶ 接手先读这一段

```text
当前任务：让 ninfer-serve.exe（Windows 原生）把后训练 Oxcoder9B 跑成可交付推理服务（五项验收）。

已完成（全部实测）：
  ① 5 prompt × 3 轮 = 15/15（内容非空）· 长 prompt 312 token 3/3 · 失败只死单请求
  ② --vision 启动 7 s；HTTP URL 图片走完 decode→image token→vision tower→文本，可复现
  ③ 普通对话（含长 prompt）正常；带 tools 内容退化属"可后续"
  ④ 冷启 7 s、长 prompt TTFT 225 ms、前缀复用命中更快
未完成：
  ⑤ 34.4 tok/s（无投机）。--spec mtp 已连破 7 层、跑到 verify 的 GDN conv，
    最后一层 = input_conv/q4_q5 三处 kValueRows=6144 / kHidden=5120（27B 常量）

交付物：
  out/kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer（7.93 GB / 738 objects / text+vision+mtp / G1=q8 gate·up）
  启动：& _tools\\run-serve.ps1        （①③④）  追加 --vision → ②   不要加 --spec mtp（当前 FATAL）

下一动作：为 input_conv/q4_q5 的 convolution.cu:19-25 / projection_mma.cu:39 /
          projection_independent.cu:19 建 9B 实例（kHidden 4096 / kValueRows 4096 / kChannels 8192），
          注意 gdn.cpp:94-96 记录过"曾因 workspace 冲突导致 prefill 全崩而回滚"，须配独立 arena 并回归 15/15。
```

---
"""

DONE_ADD = """
### 6.9 本轮（2026-11-08 12:00–20:30）新增完成项

- [x] **长 prompt NaN（≥263 token）定位并绕过**：病灶 = L03 首个 full-attention 层的 proj_k/proj_v（1024 行段），
      触发宽度在 (260,272]；修法 = 启动加 `--prefill-chunk 128`（块宽 >128 必 NaN）。
      验证：312 token prompt 3/3 通过（此前必 500→503）。
- [x] **CUDA graph 已打通**：根因是 9B MLP swiglu dispatch 里未关闭的 `cudaDeviceSynchronize`（捕获期 error 900→901）。
      验证：decode 15.3 → 36.2 tok/s（2.3×）。commit 8973a04。
- [x] **采样空候选不再打死进程**：`ops/sampling/sample/kernel.cuh:56,206` 的 `asm volatile("trap;")` 改为不发散值。
      验证：带 tools 请求从「进程 0xC0000409」→「单请求 HTTP 500，引擎存活」。commit c6faf4b。
- [x] **grammar 约束失败降级**：`text/grammar.cpp:368` 的 accept 失败不再 throw。commit 9aa848f。
- [x] **G1 量化落地**：mlp.gate/up 升 **q8**（64 张量；原定 q6，因引擎无 q6 swiglu 改用 q8，精度更高）。
      产物 formats 含 q8×34，5×3=15/15 不退化，192 token 34.4 tok/s。
- [x] **三组件产物（text+vision+mtp）生成**：`kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer`（7.93 GB，738 objects）。
      转换链：影子 HF 目录（权重硬链接）+ recipe_g1_full_gsq.py + `--components text,vision,mtp`。
- [x] **② 视觉链路打通**：`--vision` ready=True 7 s；HTTP URL 图片 → decode→image token→vision tower→文本可复现。
      data URI 的 base64 路径有引擎上游 bug（WIC: unrecognized image format），用 HTTP URL 绕过。
- [x] **⑤ 投机链路连破 7 层**（每层打印定位后修）：
      pair k=4096 / mtp attention 四合一 group（含 gate，10240 行）/ q8(10240,4096) / q8(4096,4096) /
      bf16(24576,4096) / gdn_replay_fold 放宽到 32 层 / slice 越界定位于 GDN conv 常量。
"""

NEXT_NEW = """## 7. 进行中 / 下一步（新对话先干这个）

### 7.1 当前唯一卡点（⑤ 的最后一层）

```text
现象：--spec mtp 启动通过、进入推理后
      FATAL | text/layers/0 verify columns=4: slice range out of bounds
      诊断打印：[slice-miss] dim=0 start=4096 len=6144 extent=8192

根因：GDN input_conv 的 27B 专用常量套件（三处 .cu）
  src/ops/linear_attention/gated_delta_net/input_conv/q4_q5/convolution.cu:19-25
      kHidden 5120 / kQueryRows 2048 / kKeyRows 2048 / kValueRows 6144 / kChannels 10240
  .../q4_q5/projection_mma.cu:39          kValueRows 6144
  .../q4_q5/projection_independent.cu:19  kValueRows 6144
9B 应为：kHidden 4096 / kQueryRows 2048 / kKeyRows 2048 / kValueRows 4096 / kChannels 8192
⇒ 需要为这三处建 9B 实例（模板化 or 复制实例；CMake 不 GLOB，必须原地加）
```

### 7.2 下一步动作（可直接执行）

```powershell
# 1) 三处 .cu 的常量按运行期或 9B 值分派（先只改 verify 会走的那条：
#    q4_q5/convolution.cu 的 kValueRows 与 kHidden）
# 2) 删对应 obj → 重编（改 .cu 后 Ninja 会重编，但改 .cuh/.h 必须手删 obj）
& D:\BaiduNetdiskDownload\Local-AI\_tools\build_ninfer.ps1 -Action build
# 3) 起投机
ninfer-serve.exe <产物> --max-context 4096 --greedy --host-context-mib 2048 `
  --prefill-chunk 128 --no-thinking --spec mtp --draft-tokens 3 --port 1830
# 4) 测速 + 回归
#    单流 192 token 记 tok/s（目标 ≥100；无投机基线 34.4）
#    回归：& _tools\\run-serve.ps1 跑 5×3 必须仍 15/15（prefill 不得退化）
```

### 7.3 待验证假设

- 假设 1：verify(T=4) 与 prefill 走的是**不同** conv 分派，故只改 verify 路径不会影响 prefill 的 15/15。
- 假设 2：9B 的 conv 常量换成 (4096/2048/2048/4096/8192) 后，GDN 的 slice 不再越界。
- 假设 3：投机开启后 tok/s 提升幅度取决于 mtp_top1（当前产物用 v3-mix600.step300，top1≈0.467；
  本地还有 v1-reonly top1=0.8516，若需要更高接受率可注入其 15 个 mtp 张量后重转）。
"""

LEI_ADD = """
### 9.8 本轮新增雷区（2026-11-08 12:00–20:30，只增不减）

- 现象/坑：改了 `.h` / `.cuh` 后重编，报错不消失、行为不变；原因：Ninja 不跟踪头文件依赖；
  正确做法：改头文件后必须手删对应 `.obj`（本轮 `gdn/replay/launch.h` 就踩过，删 gdn/replay 相关 40+ obj 才生效）。
- 现象/坑：converter 的 `--recipe` 传绝对路径报 `cannot load recipe file ...\\D`；
  原因：`--recipe` 支持 `file:function` 语法，按 `:` 切分，Windows 盘符被切掉；
  正确做法：把 recipe 复制到 `ninfer-master\\.agent-tmp\\` 并用**相对路径**传。
- 现象/坑：`--resource tokenizer_config.json=<path>` 不生效、产物内仍是 1100 B 精简版；
  原因：该 resource 的取值链路有内部优先级，外部参数被覆盖；
  正确做法：用影子 HF 目录（`model.safetensors` 建硬链接，只替换 json），且 tokenizer_config 必须用
  **旧产物里那份 5518 B 的完整版**（含 added_tokens_decoder + add_prefix_space），
  导出方式：`tools.artifact.reader.Artifact(...).read_object('resource/text/tokenizer_config.json')`
  （`read_range` 拿到的是封装编码、`to_json()` 只返回元数据，都不对）。
- 现象/坑：转换报 `FileExistsError: conversion output already exists`；
  原因：`.conversion.json` 残留也算已存在；正确做法：删 `<x>.ninfer` 和 `<x>.ninfer.conversion.json` 两个。
- 现象/坑：`--prefill-chunk 40` 等小值会让引擎直接打印 usage 退出；正确做法：用 128（实测可用）；
  块宽 >128 时 L03 的 proj_k/proj_v 会 NaN（长 prompt 必 500→503）。
- 现象/坑：长 prompt 输出全落 `reasoning_content`、`content` 为空；正确做法：启动加 `--no-thinking`。
- 现象/坑：带 tools 的请求内容退化为重复 token（44/94 之类恒定 id）；
  原因：prompt 长度（358 token）落在长 prompt NaN 区间，不是 tools 逻辑问题；
  正确做法：先解决长 prompt（chunk 128），再谈工具调用。
- 现象/坑：`S_NEW` 之外，`--spec mtp` 报 `missing component mtp` / `--vision` 报 `missing component vision`；
  原因：.ninfer 的组件由转换时 `--components` 决定，缺组件无法靠启动参数补；
  正确做法：重转并显式列 `--components text,vision,mtp`。
- 现象/坑：mtp 的 attention 张量被拆成多个 object 时，加载报
  `native input requires one contiguous parent region`；
  原因：引擎要求同一 WeightView 的 parts 属于**同一 parent 且行区间相邻**；
  正确做法：转换器的 group 必须把 `query+gate+key+value` **四合一**（10240 行）成同一 parent，
  且四者 format/layout/method 完全一致（否则 compatible() 不合并 → 各成独立 parent）。
- 现象/坑：`q8 linear: unsupported shape` / `bf16 linear: unsupported shape` 只说"不支持"，不说是哪个形状；
  正确做法：在 `projection/q8/q8_dispatch.cpp` 与 `projection/bf16/bf16_dispatch.cpp` 抛错前
  加 `fprintf(stderr, "[q8-miss] n=%d k=%d t=%d\\n", ...)`，一次就能拿到缺失形状。
  （这些诊断打印定位完必须删掉，别留在热路径/启动路径。）
- 现象/坑：`gdn_replay_fold: unsupported record geometry`；
  原因：`select_fold_geometry` 只认 48/36/30 层三种几何；
  正确做法：9B 是 32 层，但 head 几何（qk16/value32/conv8192）与 Layers30Heads32 相同，
  放宽 layers 判定复用即可（fold 是逐层的）。
- 现象/坑：PowerShell 里 `"run$n:"` 报「变量引用无效」；正确做法：写成 `"run${n}:"` 或字符串拼接。
- 现象/坑：`Stop-Process` 偶发「找不到进程标识符」；原因：引擎已退出；
  正确做法：`-ErrorAction SilentlyContinue`，不要当失败。
"""

HIST_ADD = """- 2026-11-08 20:30：**9B 交付形态成立** —— ①③④ 完成（15/15、对话、冷启 7s/TTFT 225ms）、
  ② 视觉链路打通（--vision + HTTP URL 图文问答可复现）；⑤ 34.4 tok/s，投机连破 7 层、
  最后一层 = GDN conv 的 27B 常量（kValueRows 6144 / kHidden 5120，三处 .cu）。
  引擎侧新增：tokenizer 缺字段早退、q8 swiglu 9B 形状、q8/bf16 projection 各 2-3 个形状、
  pair k=4096、gdn fold 32 层、mtp k∉{2048,5120} 回退非 pair。
  详见 `_work/ninfer-9b/TASKPOINT.md`（子任务级逐层记录）与 commit af914b6。
"""


def replace_block(text: str, start_marker: str, end_marker: str, new_block: str) -> tuple[str, bool]:
    i = text.find(start_marker)
    j = text.find(end_marker, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        return text, False
    return text[:i] + new_block + text[j:], True


# 1) 头部
m = re.match(r"^# TASKPOINT.*?\n---\n", src, re.S)
if m:
    src = HEADER_NEW + src[m.end():]
    print("header: ok")
else:
    print("header: MISS")

# 2) ▶ 接手先读这一段
src, ok = replace_block(src, "## ▶ 接手先读这一段", "## 1. 任务目标", READ_FIRST)
print("read_first:", ok)

# 3) §6 追加（插到 §7 之前）
i = src.find("## 7. 进行中")
if i > 0:
    src = src[:i] + DONE_ADD.lstrip("\n") + "\n" + src[i:]
    print("done_add: ok")

# 4) §7 整体替换
src, ok = replace_block(src, "## 7. 进行中", "## 8. 待办步骤", NEXT_NEW)
print("next:", ok)

# 5) §9 雷区追加（插到 §10 之前）
i = src.find("## 10. 关键文件与修改")
if i > 0:
    src = src[:i] + LEI_ADD.lstrip("\n") + "\n" + src[i:]
    print("lei_add: ok")

# 6) §13.4 更新历史追加
i = src.find("### 13.4 更新历史")
if i > 0:
    src = src.rstrip() + "\n" + HIST_ADD
    print("hist_add: ok")

p.write_text(src, encoding="utf-8")
print(f"written: {orig_len} -> {len(src)} bytes")
