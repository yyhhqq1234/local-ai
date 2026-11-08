# ninfer 9B 推理修复 · 2026-11-08

## 为什么把源文件镜像到这里

`train/lines/_shared/tools/ninfer-master/` 是**未纳入本仓库版本控制的第三方树**（`git status` 里整体是 `?? train/lines/_shared/tools/ninfer-master/`，index 内 0 个文件，无独立 `.git`）。
本次修复直接改在该树里，无法用 `git add` 进仓库，因此把**修复后的整份文件**按原相对路径镜像到本目录，便于回溯、审阅与重放。

- 上游基线：本机 checkout（仓库 `main @ 6f1a3c0` 工作区内的同一棵树）
- 镜像文件与 SHA256 前 16 位：

```text
   98807  A3F4DC0C46110183  src/models/qwen3_5/execution/text.cpp
    1201  1F9C3BD66C9D7C47  src/ops/linear/split/q4_q5/shapes/n5120_n5120_k4096/shape.cpp
   15840  13278259CD04A805  src/ops/softmax_attention/dense/causal_cache/bf16/launch.cu
   17454  6A294B5A5FBF19FC  src/ops/softmax_attention/kernels/causal/bf16/grouped_mma.cuh
```

## 根因

`Qwen3.5-9B` 的 attention 投影是一次 fused GEMM（`ops::linear_split`），四段输出
`{query 4096行, key 1024行, gate 4096行, value 1024行}`，由 `n5120_n5120_k4096` 这条 shape 承接：

```cpp
// 修复前
if (x.ne[1] <= 12)  launch_small(...);   // 4 段独立 launch，正确
else                launch_matrix(...);  // fused RowSplitGroupedMmaJob
```

`launch_matrix` 在 `full = (x.ne[1] % 16 == 0) == false` 的 partial 分支里，
每个 5120 行 job 的**尾部 1024 行（key / value 段）输出 NaN**，Q / Gate 段正常。实测：

```text
T=15 修复前: proj_q nan=0  proj_k nan=14873 l2=1.15e10  proj_gate nan=0  proj_v nan=3955 l2=6.59e09
T=15 修复后: proj_q nan=0  proj_k nan=0     l2=13485    proj_gate nan=0  proj_v nan=0    l2=8380
触发带: w∈{13,14,15} NaN；w∈{1,2,5,8,9,10,11} 正常
```

扩散链：`proj_k → norm_k → rope_k → 写入 KV cache(0x7fff) → 下一个 prefill 分块读到未写入的页
→ score NaN → softmax NaN → logits 全 NaN → 采样越界 → HTTP 500`。
单块 prefill 之所以正常，是因为首块 `first = positions[0] = 0`，K/V 全部直接取输入、不读 cache。

## 改动清单

1. **shape.cpp（功能修复，必留）**
   `launch()` 分流阈值 `x.ne[1] <= 12` → `x.ne[1] <= 15`，13–15 token 走已验证的 4 段独立路径
   （`launch_q4_range` 支持 T≤16；`launch_q5_range` 走 SIMT 自动切 token，任意 T 安全）。

2. **text.cpp（诊断，生产关闭）**
   `attn_mix()` 内加 attention 分段 dump（proj/norm/rope/attn_out + KV 位图 + 位置），
   由 `constexpr bool kAttnDiag = false;` 总开关控制；默认关闭，关闭时无 `cudaDeviceSynchronize`。

3. **launch.cu（诊断，生产关闭）**
   `bf16_kv_append_attention()` 内 `kv-entry.txt` / `kv-post.txt` 落盘，由 `constexpr bool kKvDiag = false;`
   控制；另有被读取的 `g_kv_write_*` 设备符号定义。

4. **grouped_mma.cuh（诊断残留）**
   `g_kv_write_*` 的 `extern __device__` 声明 + 写块内 `atomicAdd` 计数。当前无人读取，
   建议下次动这条 `.cuh` 时一并删除（代价极小，故未单独立即改动）。

## 重放方式

```powershell
$NM = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-master'
$P  = 'D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\patched-20261108'
Copy-Item -Recurse -Force "$P\src\*" "$NM\src\"

# 改了 .cuh 必须先删对应 obj —— Ninja 不追踪被 include 的头，否则改动不生效
Get-ChildItem 'D:\BaiduNetdiskDownload\Local-AI\_tools\ninfer-build' -Recurse -Filter *.obj |
  Where-Object { $_.FullName -match 'softmax_attention' } | Remove-Item -Force

& 'D:\BaiduNetdiskDownload\Local-AI\_tools\build_ninfer.ps1' -Action build
& 'D:\BaiduNetdiskDownload\Local-AI\_tools\accept_final.ps1' -Port 1630 -Rounds 3
```

## 验收（2026-11-08 实测，同一引擎内）

```text
5 prompt × 3 轮        =>  OK=15 FAIL=0
长生成                 =>  tok=111 chars=650，语义连贯
引擎存活               =>  15 请求后仍 alive，无 service_unavailable / 无 300s 挂死
分段 trace nan≠0 行数  =>  0（含原本必崩的 T=15）
```

## 已知未覆盖

`launch_matrix` 在 **w ≥ 16 且不是 16 的整倍**（17–31、100…）时仍走同一个 partial 分支，
本次修复只把 ≤15 拉回安全路径。长 prompt 单块 prefill 仍可能踩到，需另做加固。

## 追加 2026-11-08（round 3）：CUDA graph 打通

根因：9B MLP swiglu 路径 q4/shapes/n34816_k5120/dispatch.cpp 第 89/133 行两处未关闭的诊断块含
cudaDeviceSynchronize，捕获期是 cudaErrorStreamCaptureUnsupported(error 900)，使整个捕获 901 失效。
定位手段：cudaStreamGetCaptureInfo 分段探针（NINFER_CAP_TRACE=1），status 在 post.mlp_enter 仍为
Active，进 linear_swiglu 后作废。

附带修复：
- src/core/decode_graph.h/.cpp 新增 graph_capture_active()（进程级 atomic），BeginCapture..EndCapture 置位；
- src/core/device.cu DeviceContext::synchronize() 捕获期直接 return（stream_ 是 legacy 默认流，等价 device sync）；
- 关闭热路径诊断：text.cpp(gdn/layer dump)、dense_mlp.cpp(swiglu/delta dump)、operands.cpp([split-diag])、
  swiglu dispatch.cpp(两处 gate/up dump)。

实测：
- --no-cuda-graph：192 token / 12.3s = 15.3 tok/s
- cuda-graph    ：192 token / 5.3s  = 36.2 tok/s（2.3x）
- graph 模式 accept_final 3 轮：OK=15 FAIL=0，内容与 eager 逐字一致；长生成 111 token 正确。

