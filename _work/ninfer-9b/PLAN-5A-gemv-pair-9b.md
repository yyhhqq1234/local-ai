# ⑤-A 落地蓝本：把 q4 swiglu GEMV-pair 模板化到 9B（N=24576, K=4096）

> 目标文件：`src/ops/linear/swiglu/q4/shapes/n34816_k5120/small.cu`（223 行，已读全）
> 原则：只改常量来源与 launcher 校验，不动数学与流水线结构；`launch_q4_swiglu_small_t_tiled`（T=2..32）不动。

## 1 常量现状与 9B 取值（全部可由 N/K 推导）

| 常量 | 定义 | 27B | 9B |
|---|---|---|---|
| kN | 字面量 | 34816 | **24576** |
| kK | 字面量 | 5120 | **4096** |
| kIntermediate | kN/2 | 17408 | 12288 |
| kGroupK | 64 | 64 | 64 |
| kGroups | kK/kGroupK | 80 | 64 |
| kBytesPerGroup | 32 | 32 | 32 |
| kVecBytes | 16 | 16 | 16 |
| kGroupsPerWarpTile | 16 | 16 | 16 |
| kVecsPerWarpTile | kGroupsPerWarpTile*32/16 | 32 | 32 |
| kWarpsPerBlock | 4 | 4 | 4 |
| kBlockThreads | 128 | 128 | 128 |
| kPairsPerBlock | 4 | 4 | 4 |
| kXVecs | kK/8 | 640 | **512** |
| kTiles | kGroups/16 | 5 | **4** |

静态断言在 9B 下仍成立：`kIntermediate(12288) % 4 == 0`、`kGroups(64) % 16 == 0`、`kVecsPerWarpTile == 32`。

## 2 改动清单（4 处）

```text
A. small.cu:22-39  把 constexpr 块改成
   template <int kN_, int kK_> struct Q4PairCfg {
       static constexpr int kN = kN_, kK = kK_;
       static constexpr int kIntermediate = kN/2;
       ... 其余按上表推导，static_assert 移入结构体内 ...
   };

B. small.cu kernel 与 q4_issue_pair_tile 增加 template <class Cfg>，
   函数体内所有裸常量（kK / kXVecs / kGroups / kBytesPerGroup / kGroupsPerWarpTile /
   kTiles / kIntermediate / kWarpsPerBlock / kVecsPerWarpTile / kPairsPerBlock）
   改成 Cfg::xxx；共享数组维度改成 Cfg::（kernel 内 kK→Cfg::kK 等）。

C. small.cu:203-213  launcher 模板化
   template <int N, int K>
   void launch_q4_swiglu_gemv_pair(const Tensor& x, const Weight& w, Tensor& out, cudaStream_t s) {
       using Cfg = Q4PairCfg<N, K>;
       if (w.n != N || w.k != K || w.padded_shape[1] != K)
           throw std::invalid_argument("q4 linear_swiglu GEMV pair: unexpected weight shape");
       const int grid = Cfg::kIntermediate / Cfg::kPairsPerBlock;
       q4_linear_swiglu_gemv_pair_kernel<Cfg><<<grid, Cfg::kBlockThreads, 0, s>>>(...);
       CUDA_CHECK(cudaGetLastError());
   }

D. launch.h:10 声明改为两个显式实例（避免模板外泄到 .h 的用法扩散）：
   void launch_q4_swiglu_gemv_pair_27b(...);   // N=34816,K=5120（原行为）
   void launch_q4_swiglu_gemv_pair_9b (...);   // N=24576,K=4096（新增）
   small.cu 里各给一行显式实例化包装，代码不变。
```

## 3 dispatch 接线（`q4/shapes/n34816_k5120/dispatch.cpp`）

```text
:22  kPlans 保留 {1, launch_q4_swiglu_gemv_pair_27b}（27B 行为不变）
新增：rows==24576 && k==4096 且 x.ne[1]==1 时 → launch_q4_swiglu_gemv_pair_9b
     其余 tokens（含 prefill）继续走 materialized —— 不动已验证路径
:36 的 supported 判断已包含 (24576,4096)，无需改
```

## 4 验收三口径（缺一不可）

```text
① 数值对拍：同一 prompt、同一 seed，GEMV 与 materialized 的首 token logits 必须一致
   （用 _tools 里现成的 logits dump 或 sylogits 对比；不一致即回滚）
② 回归：& _tools\run-serve.ps1（chunk128 + no-thinking）→ 5×3 必须仍是 15/15
③ 性能：_tools/bench_decode.ps1 -Graph，对比基线 36.8 tok/s
```

## 5 回滚

```text
ninfer-master 未纳入 git；改前先
  cp small.cu small.cu.bak-5a && cp launch.h launch.h.bak-5a && cp dispatch.cpp dispatch.cpp.bak-5a
回滚：把 .bak-5a 覆盖回去，删对应 .obj 重编（改 .cu 后必须删 obj，否则 Ninja 不重编）
```

## 6 构建系统事实（round 85 实测，修正此前的"可新建目录"假设）

```text
src/ops/CMakeLists.txt 只显式列了 weight_input.cpp（15 行规模）；
顶层 CMakeLists.txt 无 file(GLOB *.cu)。
⇒ 新增 small9.cu / n24576_k4096/ 目录不会被收录进构建（或需要改 CMake，风险外溢）。
⇒ 5-A 必须**原地模板化** small.cu，不能靠复制文件走捷径。
```

## 7 原地模板化的精确替换表（下一轮机械执行）

```text
模板参数命名：template <int TN, int TK>
替换（整个匿名 namespace 内 + kernel 体内）：
  kN            -> TN
  kK            -> TK
  kIntermediate -> (TN / 2)   ← 建议定义 static constexpr int kIntermediate = TN/2; 保留原名
  kGroups       -> 保留原名，定义 static constexpr int kGroups = TK / kGroupK;
  kXVecs        -> 保留原名，定义 static constexpr int kXVecs = TK / 8;
  kTiles        -> 保留原名，定义 static constexpr int kTiles = kGroups / kGroupsPerWarpTile;
其余（kGroupK/kBytesPerGroup/kVecBytes/kGroupsPerWarpTile/kWarpsPerBlock/kBlockThreads/
      kPairsPerBlock/kVecsPerWarpTile）值不变，保持全局 constexpr 即可。
做法：把 "constexpr int kN" / "constexpr int kK" 两行删掉，
      在模板结构体内重新定义 kIntermediate/kGroups/kXVecs/kTiles 四个派生常量，
      kernel 与 q4_issue_pair_tile 加 template <int TN, int TK>，
      launcher 加同名模板参数并显式实例化 27B/9B 两个包装函数。
```

## 8 上下文预算提示

```text
本任务需要：改 3 个文件（约 12 处常量 + 2 处签名 + 1 处 dispatch 分支）
          + 删 obj 重编（约 4 分钟）+ 三项验收（对拍 / 15×3 / bench，约 5 分钟）。
建议在上下文充足的会话里连续完成；中途上下文不足时，
务必先确认 `git status` 干净与 .bak-5a 备份可用，再交回，避免留下半改状态。
```
