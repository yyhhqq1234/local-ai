# ninfer 9B · 长 prompt NaN · round 47 决定性证据

## 桩位终于正确（关键经验）

```text
逐层 NaN 统计必须放在 run_layers 的 **eager 分支 continue（:1401）之前**。
放在 catch 之后的“分支汇合处”无效：eager 在层末直接 continue，dense(非 MoE) 模型只走 eager。
gate 用 T>=200 只看长 prompt，避免短 prompt 刷屏。

实测输出（chars=470 → T=263）：
  L00 prefill T=263 nan=0
  L01 prefill T=263 nan=0
  L02 prefill T=263 nan=0
  L03 prefill T=263 nan=16384   ← 首个 NaN 层（L03 = [linear×3, full] 的第一个 full-attention 层）
  L04…L31 全 NaN
对照：T=260 的同一请求 OK
```

## L03 内部的分段证据（attn_mix 桩，T=263）

```text
proj_q    nan=0        l2=89307     ← Q 正常
proj_k    nan=63276    l2=2.60e10   ← K 大面 NaN
proj_v    nan=3955     l2=1.89e10   ← V 有 NaN
proj_gate nan=0        l2=24925     ← gate 正常
norm_k / rope_k / attn_out → 全 NaN（继承 proj_k）
kv post map = 32 位全 N
```

即：**4096 行的 q/gate 段正常，1024 行的 k/v 段坏** —— 与 7e81e48（w∈13,14,15）完全同一签名，
只是这次的触发宽度是 263（走 `launch_matrix`）。

## 两条绕行已被实测否掉（勿重试）

| 绕行 | 结果 |
|---|---|
| `shape.cpp` 阈值 `<=15` → `<=512`（全走 4 段独立 launch） | FAIL（已回滚） |
| `--prefill-chunk 256` | FAIL |

## 下一轮（唯一未试方向）

```text
proj_k / proj_v 来自 5120 行 q4/q5 父权重的后 1024 行（sub_weight 行偏移 4096）。
两条路径都在「后 1024 行 + T≈263」组合上出错 → 怀疑点：
  · K/V 段的 Q4/Q5 反量化 epilogue，或
  · sliced-K 的 M 方向切分（M=1024）与 T 尾块对齐
下一步：
1. 对 T=260（OK）与 T=263（FAIL）各 dump proj_k 前 128 个元素，定位坏元素从第几个 token 起；
2. 看 launch_q4_range 里 T<=16 / <=24 / 其它 三档分别命中的实例，
   确认 263 命中的是 SlicedK4096T24 之外的哪一个（>24 走的是 SlicedK4096T4 通用实例）；
3. 若坏行按 24/32 的倍数起算，即切片 M 方向 stride 假设错，改该实例或加一次 T 断言。
```

## 当前开关状态（全部关闭，可编译）

```text
text.cpp:863   kAttnDiag = false
text.cpp:1368  逐层 dump gate = false && …
text.cpp:1430  kLayerDiag = false
```
