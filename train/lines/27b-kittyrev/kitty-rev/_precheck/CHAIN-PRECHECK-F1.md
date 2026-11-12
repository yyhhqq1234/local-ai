# CHAIN-PRECHECK-F1 · 关闭记录

- 时间：2026-10-24 01:56 (Asia/Shanghai)
- 上游：CHAIN-PRECHECK.md 的唯一 FAIL（llama-cli 缺失）
- 状态：**CLOSED**

## 处置

由 lead 执行（我的写域不含 lc/）：
```
make -C /root/autodl-tmp/lc/build-cuda89 llama-cli -j32     # log: $R/logs/v4/BUILD-CLI.log
```

## 实测验收（chain-op 复核，01:52–01:56）

```
$ ls -l /root/autodl-tmp/lc/build-cuda89/bin/llama-cli
-rwxr-xr-x 1 root root 1499240 Oct 24 01:52 .../llama-cli

$ LD_LIBRARY_PATH=…/bin llama-cli --version
version: 0.7.0-dev (build 0, commit unknown)
built with GNU 11.4.0 for Linux x86_64

$ ldd llama-cli | grep -E "libllama|libggml|not found"
libllama-cli-impl.so    => …/bin/libllama-cli-impl.so
libllama-server-impl.so => …/bin/libllama-server-impl.so
libllama-common.so.0    => …/bin/libllama-common.so.0
libllama.so.0           => …/bin/libllama.so.0
libggml.so.0            => …/bin/libggml.so.0
libggml-base.so.0       => …/bin/libggml-base.so.0
libggml-cpu.so.0        => …/bin/libggml-cpu.so.0
libggml-cuda.so.0       => …/bin/libggml-cuda.so.0
（无 not found）
```

附：编译同时带出了 libllama-cli-impl.so 与 libllama-server-impl.so，说明 tools/cli 与 tools/server
公共目标一并链接成功，`llama-cli` 可直接跑 CUDA 推理，M1.5 探针的硬件路径成立。

## 新版链脚本契约（$R/tools/chain_repair.py 13577 B @01:53）逐点核对

| 点 | 位置 | 实测代码 |
|---|---|---|
| M1.5 不降级 | L154-163 | 只找 llama-cli/llama-simple/main，缺失直接 stop()，无 SKIPPED 分支 |
| M1.5 正文切片 | L168 | body = out.split("llama_perf")[0]（F4：避免性能行导致 cjk=0 误杀） |
| M1.5 失败即停 | L189 | stop(f"M1.5 探针失败 {payload}") |
| M4 硬断言 | L243-244 | "load_imatrix" not in out → stop(...) |
| M5 查 rc | L255-259 | splice_new rc!=0 → stop（F2：不再只看产物存在） |
| 清盘开关 | L306-307 | --free 与 --free-merged 分离；我只用 --free |
| M6 门 | L276-298 | 无产物 stop / >10 GiB stop / NAME 不含 -v4r stop / objects 不在 700-900 stop（期望 ~806） |

## 链路契约（定稿，按 lead 决策）

```
M0 → M1(bf16) → M1.5(探针)
   → [lead 手删 merged-v4，df≥66G，我不动]
   → M2(q8_0) → M3(imatrix) → [--free 删 q8_0]
   → M4(IQ2_S, 含 --imatrix + 64 层 ssm_alpha/ssm_beta=q8_0) → [--free 删 bf16]
   → M5(splice, ref=ref_sparse.gguf) → M6(convert, ≤10 GiB)
```

起链命令（待 [SIGNAL] merge done）：
```
cd /root/autodl-tmp/kitty-rev && setsid nohup /root/miniconda3/bin/python -u tools/chain_repair.py --free > logs/v4/CHAIN-R.log 2>&1 &
```

## 剩余风险

1. M1.5 是全链唯一权重正确性门 —— FAIL 立即停链并最高优先上报，不重试。
2. M2 起跑需 df ≥ ~28 G 余量（lead 删 merged 后应 ≈66 G 可用，满足）。
3. 硬截止 06:40，当前 01:56，剩 4h44m；链路预算 ≈3h35m。
