# ninfer 9B · 可用配置与验收结果（2026-11-08 round 54-56）

## 可用启动配置（实测 8/8 通过）

```powershell
& _tools\run-serve.ps1                      # 等价于下面这行
ninfer-serve.exe <model.ninfer> --max-context 4096 --greedy --host-context-mib 2048 \
  --prefill-chunk 128 --no-thinking --port 1610
```

两个参数为何必需：
- `--prefill-chunk 128`：块宽 >128 时 L03（首个 full-attention 层）的 proj_k/proj_v（1024 行段）NaN
  → logits 越界 → HTTP 500 → 引擎 503。压到 128 后 310/360 token 请求均可完成。
- `--no-thinking`：否则输出全落 reasoning_content，message.content 为空（长 prompt 尤其明显）。

## 验收实测（round 56）

```text
S-2+2  OK len=14     S-hello OK len=15    S-gdn  OK len=288
S-py   OK len=52     S-unit  OK len=648
LONG1  OK prompt_n=312 len=100     ← 长 prompt 跑通（默认分块下必 500）
LONG2  OK prompt_n=9   len=100     ← 前缀复用生效（KV checkpoint）
LONG3  OK prompt_n=9   len=100
==== 合计 OK=8 FAIL=0 ====
```

## 仍未达标

```text
② 多模态：--vision → FATAL missing component vision（产物缺组件，需重做 .ninfer 转换）
③ 工具调用：带 tools 请求 200 但内容退化（语法约束路径），普通对话可用
⑤ 速度：36.8 tok/s（CUDA graph 已 2.3×）；再上需 k4096 swiglu GEMV-pair kernel 或带 MTP 的产物
```


## round 58 追加：严格口径 5x3 验收

```text
启动: --prefill-chunk 128 --no-thinking
判据: HTTP 200 且 message.content 长度 > 0 才记 OK（比之前更严，空内容不算过）
结果: ==== 5x3 => OK=15 FAIL=0 ====
```

至此 ① 达标（内容非空 15/15），加 round 56 的「长 prompt 312 token 3/3 + 前缀复用 prompt_n=9」。

## 仍未达标（两条都不是调参可解）

```text
② 多模态: --vision -> FATAL missing component vision（产物缺组件）
   需要重做 .ninfer 转换，把 vision tower 打进产物 —— 转换侧工程
⑤ 速度: 36.8 tok/s（graph 已 2.3x）
   A) 新写 k4096 swiglu GEMV-pair kernel（27B 版本 kN/kK/kIntermediate 为编译期常量）
   B) 重做带 MTP 头的产物后启用投机解码（--spec mtp 当前因缺组件直接 FATAL）
```

## 5-A 路线：k4096 swiglu GEMV-pair 的常量映射（round 60 读源码确认）

```text
src/ops/linear/swiglu/q4/shapes/n34816_k5120/small.cu:22-39
  kN = 34816 -> 9B 24576      kK = 5120 -> 9B 4096
  kIntermediate = kN/2 -> 12288    kGroupK = 64（同）
  kGroups = kK/64 -> 27B 80, 9B 64    kGroupsPerWarpTile = 16（同）
  kTiles = kGroups/16 -> 27B 5, 9B 4
  kPairsPerBlock=4 / kBlockThreads=128 / kVecsPerWarpTile=32（同）
=> 只需把 kN / kK 模板化，其余常量全部由它们推导；launch_q4_swiglu_gemv_pair 的
   `w.n != kN || w.k != kK` 校验随之变成特化后校验。
```

实施四步：
1. small.cu 常量包成 template<int N,int K> Config，kernel/launcher 按 Config 实例化；
2. shape.cpp 的 k==4096 分支：tokens==1 走 q4_swiglu_gemv_pair<24576,4096>，其余 tokens 仍走 materialized；
3. 数值对拍：同 prompt 下 GEMV 与 materialized 首 token logits 一致；
4. 通过后用 _tools/bench_decode.ps1 -Graph 测 tok/s（从 36.8 起往上）。
