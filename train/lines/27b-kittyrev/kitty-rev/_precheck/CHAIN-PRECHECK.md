# CHAIN-PRECHECK · v4 交付①重做（merge→convert 链路）

- 时间：2026-10-24 01:49–01:52 (Asia/Shanghai)
- 执行者：chain-op（石井执行层）
- 远端：123.127.15.155 (AutoDL, RTX 4090 24564 MiB, 128 core, load 7.5)
- R = /root/autodl-tmp/kitty-rev

## 总判：8 项中 7 PASS / 1 FAIL

| # | 项 | 结果 | 实测 |
|---|---|---|---|
| 1 | llama.cpp 三件套 | **FAIL** | llama-imatrix OK 225328 B；llama-quantize OK 17856 B；**llama-cli 不存在** |
| 2 | splice ref | PASS | /root/autodl-tmp/ref/ref_sparse.gguf 9,607,981,120 B = 8.95 GiB（≈9.6 GB） |
| 3 | convert --model 目录 | PASS | $R/cfg-vision：chat_template.jinja, config.json, generation_config.json, tokenizer.json, tokenizer_config.json |
| 4 | 转换器 | PASS | $R/ninfer-all-master/tools/convert：__init__.py, __main__.py, __pycache__, config_fields.py, gemma4.py |
| 5 | calib-v4.txt | PASS | 5,079,336 B = 4.84 MiB（预期≈5.08 MB，一致）；head-3 为数学题+解答，PE 对齐可用 |
| 6 | 网络加速 / 磁盘 | PASS | TURBO_PRESENT；/dev/md0 200G 用 79G 可用 122G (40%) |
| 7 | 三个脚本 | PASS | chain_repair.py 11043 B (Oct 24 01:46)；convert_gguf_safe.py 3461 B；splice_new.py 6880 B |
| 8 | 磁盘预算（峰值 109.4 G） | PASS | 可用 122 G ≥ 115 G，余量 12.6 G |

## 1 项 FAIL 的定位与根因

```
build-cuda89/bin/ 实际内容：
  libggml-base.so / libggml-cpu.so / libggml-cuda.so / libggml.so
  libllama-common.so / libllama.so / libllama-quantize-impl.so
  llama-imatrix   (225328 B, Oct 23 00:29)
  llama-quantize  (17856 B,  Oct 23 00:29)
  ✗ 无 llama-cli

build-cuda89/CMakeCache.txt 关键项：
  CMAKE_BUILD_TYPE      = Release
  GGML_CUDA             = ON
  LLAMA_BUILD_EXAMPLES  = ON     ← 已开启，只是没有编译该 target
  LLAMA_BUILD_TOOLS     = ON
  LLAMA_BUILD_SERVER    = ON
  LLAMA_BUILD_TESTS     = ON

make -C build-cuda89 help 中存在 target：
  llama-cli / llama-cli-impl / llama-server / llama-perf / llama-bench
  （examples/ 下已无 cli|main|server 子目录 → 新目录结构，target 名仍为 llama-cli）

全盘搜索：which llama-cli llama-server llama-bench main 全空；
/usr/local/bin、/root/miniconda3/bin 均无 llama*。
```

结论：**不是路径写错，是 llama-cli 从未编译**（10-23 00:29 那次构建只出了 imatrix/quantize）。
M1.5 引擎探针（唯一能判权重对错的门）硬依赖它，不解决则链到 M1.5 必停。

## 等价路径（三选一，均需 lead 授权，因为会写到 $R 之外的 lc/build-cuda89/）

1. **增量补编译（推荐，最小改动）**
   ```
   make -C /root/autodl-tmp/lc/build-cuda89 llama-cli -j32
   ```
   复用已编译的 libllama/libggml/libllama-common 与 CUDA 对象，只编 examples 里 cli 相关翻译单元，预计 1–4 分钟，产物直接落在 build-cuda89/bin/llama-cli。
   风险：若 cli 源依赖未编译的 examples 公共目标，make 会顺带编译（仍在分钟级）。

2. 独立 build 目录 `-B` 全新配置编译（更慢 10–20 min，且要重编 CUDA，不划算）。

3. 放弃 M1.5，用 imatrix/quantize 之外的手段验证权重（例如量化后抽样反量化统计、或 M6 后起引擎跑一句）——但这两者都不能在 bf16→q8 之前判"权重对不对"，判据等级下降，**不建议**。

## 建议动作顺序

```
1) 授权后：make -C /root/autodl-tmp/lc/build-cuda89 llama-cli -j32
2) 验收：ls -l build-cuda89/bin/llama-cli && ldd | grep -E "libllama|libggml"
3) 干跑：llama-cli --version（CUDA init 自检）
4) 再起 chain：cd $R && setsid nohup /root/miniconda3/bin/python -u tools/chain_repair.py --free > logs/v4/CHAIN-R.log 2>&1 &
```

## 其余确认到的环境事实（链路相关）

```
merged-v4        : 尚未生成（ls: No such file or directory）→ 符合"merge 未开始"，不提前起链
$R/gguf          : 已存在，含 mtp-spliced/（空目录，M5 拼头用）
$R/logs/v4       : 已存在；.markers/ 与 .freed 在
$R/logs/v4 历史  : NIGHT-RUN.log(8201B 00:25) MERGE-EXPORT.log(9968B) POST-CHAIN.log(47719B) REBUILD.log(401774B)
nproc 128, 4090 24564 MiB 单卡
```

## 磁盘预算复核

```
链路峰值 = merged 55.6 + bf16 53.8 = 109.4 G
当前可用 122 G  →  余量 12.6 G  →  PASS（≥115 G）
注意：q8_0 阶段（M2）在 bf16 仍在盘上时需要额外 ≈14.5 G，
      M2+M3 期间峰值 ≈ bf16 53.8 + merged 55.6 + q8 14.5 = 123.9 G > 122 G
      → 必须在 M2 前释放 merged（或先删 bf16 再量化，但 imatrix 需 q8 输入）
      → 建议：M2 起跑前 du -sh 实测，若 <20 G 余量则先删 merged-v4（lead 决策）
```

## 硬截止

北京时间 **06:40** 云端停机。当前 01:52，剩余 ≈ 4 h 48 min。
按 M1(≈40min)+M1.5(5min)+M2(≈30min)+M3(≈60min)+M4(≈35min)+M5(5min)+M6(≈40min) ≈ 3 h 35 min，
余量约 1 h 10 min，够用但无重复试错空间；任一 G 门 FAIL 立即停并上报。
