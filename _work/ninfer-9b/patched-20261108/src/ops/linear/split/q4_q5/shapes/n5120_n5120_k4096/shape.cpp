#include "ops/linear/split/q4_q5/shapes/n5120_n5120_k4096/launch.h"

namespace ninfer::ops::detail::linear_split::q4_q5_n5120_n5120_k4096 {
namespace {
void launch(const Tensor& x, Weights weights, std::span<const Tensor> outputs, MemoryArena*,
            cudaStream_t stream) {
    // [9B 修复] 13..15 token 走进 launch_matrix 的 partial 分支时，
    // qk/value 两个 RowSplit job 的尾部 1024 行（key/value 段）输出 NaN，
    // 进而经 norm_k→rope_k→KV cache 污染整个分块 prefill。
    // 15 及以下一律走已验证的 4 段独立路径（launch_q4_range 支持 T<=16，
    // launch_q5_range 走 SIMT 自动切 token，任意 T 安全）。
    if (x.ne[1] <= 15)
        launch_small(x, weights.first, *weights.second, outputs, stream);
    else
        launch_matrix(x, weights.first, *weights.second, outputs, stream);
}
} // namespace
} // namespace ninfer::ops::detail::linear_split::q4_q5_n5120_n5120_k4096

namespace ninfer::ops::detail::linear_split {
const SplitShape kQ4Q5SplitN5120N5120K4096{
    5120, 4096, kSplitRows<4096, 1024, 4096, 1024>, q4_q5_n5120_n5120_k4096::launch, nullptr, 5120};
} // namespace ninfer::ops::detail::linear_split




