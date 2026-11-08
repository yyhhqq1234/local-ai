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

## round 86 决定性结论：⑤ 不能用 GEMV kernel 解决（物理带宽下限），②⑤ 合并为一个动作

### 实测（本轮）
```text
单流 192 token：tok=192 sec=5.54 tps=35.2
4 并发聚合    ：total_tok=768 wall=22.16s aggregate_tps=34.7  ← 与单流相同
⇒ 引擎按请求串行（单 lane），聚合吞吐不随并发提升
```

### 带宽账（为什么 100 tok/s 单流不可达）
```text
9B q4 权重 5.81 GiB，每生成 1 token 必须完整读一遍
35 tok/s × 5.81 GiB ≈ 203 GB/s（实测占用率约 23-26%）
100 tok/s 需要 ≈ 581 GB/s ≈ 峰值的 65-75% —— 单纯优化 kernel 得不到，
GEMV-pair 只省 launch 与 shared 交换，**不减少权重读取量**，收益上限约 35→45 tok/s
⇒ 5-A（k4096 GEMV-pair）方向作废，即使做完也到不了 100
```

### 正确路线：投机解码（每步产出多 token，摊薄权重读取）
```text
期望：draft=3、接受率 ~0.7 → 每步 ≈2.8 token → 35 × 2.8 ≈ 98-100 tok/s
前提：.ninfer 必须带 MTP 头（当前 --spec mtp / dflash 均 FATAL missing component）
⇒ ⑤ 的唯一出路 = 重做产物
```

### ② 与 ⑤ 合并：一次转换同时打入 vision + mtp
```text
现状：--vision → missing component vision；--spec mtp → missing component mtp
     两者都是"产物缺组件"，同一次 .ninfer 转换即可同时解决
产出：oxcoder9b-merged-v2.ninfer（含 text + vision + mtp）
验后：② 图片问答 1 例；⑤ --spec mtp --draft-tokens 3 测 tok/s
```

### 保留的有效结论
```text
· 5-A 蓝本与备份保留（.bak-5a），但优先级降为 P3（可作 45 tok/s 的一档小优化）
· 已确认 CMake 不 GLOB：任何新 .cu 都需原地改，不能靠加文件
```

