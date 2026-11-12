import io
import os

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"

STATUS = """
## 结项状态（2026-11-12）

```text
项目状态：结项（本地部署成立，训练线归档）
仓库规模：32.12 GB · 74,000 文件 → 清理后（原 286.92 GB，两轮共删 236.9 GB）
```

| 交付物 | 形态 | 体积 | 状态 |
|---|---|---|---|
| 9B 主模型 | `models/9b/gguf/kittyrev9b-Q5_K_M-im.gguf` | 6.19 GB | ✅ 生产（llama.cpp CUDA，decode 70–75，PPL 3.708） |
| 27B 保底模型 | `engines/ninfer-27b/…/Huihui-…-Swift-1.5-IQ2_S-mtp.ninfer` | 9.55 GB | ✅ 可用（NInfer，decode 68，MTP 75%） |
| DSH 适配器 | `plugins/dsh-local-ai/` | ~0 GB | ✅ 双引擎接入（8080 复用，`engines/switch-model.py` 切换） |
| 训练线 | `train/lines/` | 10.88 GB | 归档（数据 / 脚本 / 校准集 / imatrix 全留） |
| v6 权重 | — | — | ❌ 2026-11-12 误删，见 `docs/v6-rebuild.md` |

```text
引擎：engines/llama-cpp（9B，llama-server 8080）· engines/ninfer-27b（27B，start-27b.py 8080）
切换：python engines/switch-model.py {status|9b [fast|128k|256k]|27b|stop}
      9B 三档：fast 8k/75 tok/s · 128k/44 tok/s · 256k 主机KV/20 tok/s
```
"""

# README：置顶结项状态
p = os.path.join(ROOT, "README.md")
s = io.open(p, encoding="utf-8").read()
if "## 结项状态（2026-11-12）" not in s:
    s = STATUS.strip() + "\n\n---\n\n" + s
    io.open(p, "w", encoding="utf-8").write(s)
    print("README 结项状态置顶")

# CLAUDE.md：补结项与重建入口
p = os.path.join(ROOT, "CLAUDE.md")
s = io.open(p, encoding="utf-8").read()
s = s.replace("## 目录速查", """## 结项（2026-11-12）

```text
交付：9B GGUF（models/9b/gguf，llama.cpp）+ 27B .ninfer（engines/ninfer-27b，NInfer）
切换：python engines/switch-model.py status|9b|27b
v6 权重误删，重建见 docs/v6-rebuild.md
```

## 目录速查""")
s = s.replace("engines/                    推理引擎（llama-cpp 用于 9B · ninfer-27b 用于 27B）",
              "engines/                    推理引擎 + switch-model.py 切档脚本")
s = s.replace("models/                     已交付模型（仅 llama.cpp GGUF：9b/gguf Q5_K_M-im / Q6_K / Q8_0）",
              "models/                     已交付模型（仅 9b/gguf/kittyrev9b-Q5_K_M-im.gguf）")
io.open(p, "w", encoding="utf-8").write(s)
print("CLAUDE 更新")

# AGENTS.md：文档索引补 v6-rebuild
p = os.path.join(ROOT, "AGENTS.md")
s = io.open(p, encoding="utf-8").read()
s = s.replace("`docs/training.md`（后训练）· `docs/operations.md`（运维与联动）· `docs/plans.md`（两条线计划）·",
              "`docs/training.md`（后训练）· `docs/operations.md`（运维与联动）· `docs/plans.md`（两条线计划）·\n`docs/v6-rebuild.md`（v6 重建计划）·")
io.open(p, "w", encoding="utf-8").write(s)
print("AGENTS 索引更新")

# docs/plans.md：顶部加结项 + 指向 v6-rebuild
p = os.path.join(ROOT, "docs", "plans.md")
s = io.open(p, encoding="utf-8").read()
if "结项" not in s[:2000]:
    head = """# 计划（两条训练线）

> **2026-11-12 结项**：9B（KittyRev-OxCoder）已交付 llama.cpp GGUF 生产；
> 27B 使用 Huihui-Swift IQ2_S（NInfer）；v6 权重误删，重建计划见 [`v6-rebuild.md`](v6-rebuild.md)。
> 本文件保留两条训练线的完整历史计划，作为重建与复盘依据。

"""
    s = head + s
    io.open(p, "w", encoding="utf-8").write(s)
    print("plans 结项头")

# docs/operations.md：补切档运维
p = os.path.join(ROOT, "docs", "operations.md")
s = io.open(p, encoding="utf-8").read()
if "switch-model.py" not in s:
    s += """

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
"""
    io.open(p, "w", encoding="utf-8").write(s)
    print("operations 切档段")
print("docs 全部更新完成")
