# PRUNE-RECORD — train/ 清理记录

> 2026-10-26 20:0x。清理动机：为 9B 双能力后训练腾空间（阶段 0 需 ~18 GB 基座 +
> 合并中间件 ~18 GB）。清理原则：只删**可恢复**或**可重生成**的项，
> 交付件与训练数据一律不动。

## 已删

| 项 | 大小 | 判定依据 | 恢复路径 |
|---|---|---|---|
| `local-pack/kittyrev-local-pack-v4.tar` | 25.4 GiB | 27B 后 16 层合并产物的**归档**，未解包（`merged-layers/` 只在 tar 内）；对 9B 项目无用；`.gitignore:75` 已忽略 | 由 `kitty-rev/logs/v5/` 记录的 merge 流程重生成；云端 AutoDL `/root/autodl-tmp/kitty-rev/` 有原始产物 |
| `local-pack/qwen3.8-27b-kittyrev-v5-iq2s-mtp.ninfer` | 9.88 GiB | 27B v5 推理产物。现役引擎加载的是 `ninfer-27b-kv-stream-3arch-20261019/model/qwen3.8-27b-kittyrev-v6-*.ninfer`（10.6 GB），v5 为上一代 | 云端 `/root/autodl-tmp/kitty-rev/ninfer-v5/`（DELIVERY.md §7 记录）；本机 `*.conversion.json` 元数据保留 |
| `train/tmp/*` | ~900 KiB | 网页抓取残留（gitcode/gitee/jdg/lcz 的 html/json、探测文本） | 无需恢复 |
| 各处 `__pycache__`（`.venv` 内除外） | ~1 MiB | 字节码缓存 | 自动重建 |

## 保留（不动）

| 项 | 大小 | 理由 |
|---|---|---|
| `.venv/` | 3.1 GiB | 训练环境，阶段 2 直接用 |
| `tools/ninfer-master/` | 762 MiB | converter 依赖的 venv 与上游镜像 |
| `tools/ninfer-convert/` | 195 MiB | 转换器 + 已补的 9B recipe |
| `kitty-rev/` | 339 MiB | RE 训练数据（forge/forge2）、评测集、日志 |
| `local-pack/adapter_model.safetensors` | 146 MiB | 27B v5 adapter 成品 |
| `local-pack/*.conversion.json` | 0.9 MiB | v5/v6 转换元数据（判断产物构成用） |
| `local-pack/DELIVERY.md` | 7.4 KiB | v5 交付说明与回滚步骤 |
| `data/mix-re.jsonl` | 656 KiB | 本轮生成的 RE 训练集 |
| POSTTRAIN-OXCODER9B.md / scripts/*.py | — | 9B 后训练链 |

## 清理后体积

```text
清理前  40 GiB
清理后  ≈4.6 GiB（.venv 3.1 + tools 0.94 + kitty-rev 0.33 + 其余）
释放    ≈35.4 GiB
```

## 若要回滚 v5

`DELIVERY.md` §7 已写明：v5 与 v4r 的差异包含引擎版本依赖（当前 v0.6.0 强制要 vision 组件，
换回 v4r 需同时回滚引擎）。v5 本身重新获取 = 从云端 AutoDL 实例拷 `/root/autodl-tmp/kitty-rev/ninfer-v5/`。
