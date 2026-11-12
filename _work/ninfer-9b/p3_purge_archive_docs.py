import io
import os

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"

# README：去掉 _archive 描述
p = os.path.join(ROOT, "README.md")
s = io.open(p, encoding="utf-8").read()
s = s.replace("_work/           过程产物：ninfer-9b 实验脚本 · _research · _archive（md 归档 zip）· session-audit",
              "_work/           过程产物：ninfer-9b 实验脚本 · _research · session-audit")
io.open(p, "w", encoding="utf-8").write(s)

# train/README：删掉归档段与 logs 说明
p = os.path.join(ROOT, "train", "README.md")
s = io.open(p, encoding="utf-8").read()
s = s.replace("| `logs/_archive/` | 过程日志归档（逐轮监控 / 旧版阶段报告，zip） |\n", "")
s = s.replace("""## 已归档（不再更新）

- `lines/27b-kittyrev/kitty-rev/logs/v4|v5|v6|v7/` → `logs/_archive/kittyrev-logs-*.zip`
- `lines/27b-kittyrev/kitty-rev/logs/*.md`（过程交接 / 自测） → `logs/_archive/kittyrev-logs-rest.zip`
- `logs/*.md`（逐轮监控与阶段报告） → `logs/_archive/train-logs.zip`
- 根目录过时的结论报告（GEN4 / mix-v5 / R3 等） → `logs/_archive/train-root-obsolete.zip`
""", """## 已清理（2026-11-12 结项）

过程日志与旧版结论报告已全部删除，不再保留归档：
- `lines/27b-kittyrev/kitty-rev/logs/v4|v5|v6|v7/` 逐轮日志
- `lines/27b-kittyrev/kitty-rev/logs/*.md` 过程交接与自测记录
- `logs/*.log|*.json` 训练 / 评测 / 监控日志（417 个）
- 根目录旧版结论报告（GEN4 / mix-v5 / R3 / 2A-ACCEPTANCE 等）

保留的只有方法论文档（PITFALLS / EVAL-PROTOCOL / PREFLIGHT / ANTI-MEMORIZATION / TRAINING-LINEAGE）
与可复现的数据、脚本、量化实现。
""")
io.open(p, "w", encoding="utf-8").write(s)

# TASKPOINT 追加清理记录
tk = os.path.join(ROOT, "TASKPOINT.md")
add = """

## 2026-11-12 23:35 · 归档内容全部删除

```text
按操作者要求，已归档的过程内容不再保留：
  删除 train/logs/_archive/ 下全部 zip（8 个：kittyrev-logs-v4/v5/v6/v7/_v4selftest/rest、
                                    train-logs、train-root-obsolete）
  删除 _work/_archive/ 下 md 归档 zip（research-notes / session-audit / ninfer-9b-notes /
                                    curl-sdk-docs / ninfer-27b-docs / root-logs-20261101）
  删除 TASKPOINT.md.bak-* 备份
  删除 train/logs/ 全部过程日志与中间 json（417 个文件，73.5 MB）
  删除 _work/ 下 66 个一次性探针脚本、9 个临时目录（tmp/scratch/toolout/whlprobe/dl/ref/archive/…）、
       4 个零散 zip（cmake2/curl-win/ffmpeg/ffmpeg-dev）

保留：
  train/ 6 份方法论文档 + 数据 + 脚本 + quant
  _work/ninfer-9b（实盘脚本）· _work/session-audit（排障依据）· _work/_research（调研备案）
  engines/（llama-cpp + ninfer-27b 运行时与 27B 模型）· models/（9B GGUF）· plugins/
D 盘可用：262 GB
```
"""
io.open(tk, "a", encoding="utf-8").write(add)
print("docs updated")
