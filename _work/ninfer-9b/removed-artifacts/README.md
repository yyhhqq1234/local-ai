# 已删除产物记录

## oxcoder9b-merged.ninfer（2026-11-09 删除）

```text
路径    train/lines/9b-oxcoder/out/oxcoder9b-merged.ninfer
体积    5.83 GiB（释放后 D: 104.06 → 109.89 GB）
对象    391 · 组件仅 text · 量化 bf16 177 / fp32 48 / q4 64 / q5 96 / q8 2
来源    merged-2b-nsfw-mtp-tuned-v3（recipe: qwen3_5_9b_gsq，device cpu，41.1 s）
删除理由 与 G1 产物同基座但缺 vision/mtp、gate/up 仍 q4（leak 0.1333 超标），已被
        kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer 完全取代
保留    .conversion.json 已存本目录（历史凭据）
```

**重建方法（需要时）**

```powershell
cd D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-master
& D:\BaiduNetdiskDownload\Local-AI\train\.venv\Scripts\python.exe -m tools.convert `
  --model "D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\models\merged-2b-nsfw-mtp-tuned-v3" `
  --recipe qwen3_5_9b_gsq --components text `
  --out "D:\BaiduNetdiskDownload\Local-AI\train\lines\9b-oxcoder\out\oxcoder9b-merged.ninfer"
# 约 41 s（device cpu）/ 更快用 --device cuda
```

**连带改动**：`_tools` 下 6 个脚本的模型默认值已从 oxcoder9b-merged 改为
kittyrev-oxcoder9b-nsfw-gate-full-GSQ（各留 `.bak-merged-del` 备份），
替换后 `accept_final.ps1 -Rounds 1` 冒烟 `OK=5 FAIL=0`。
