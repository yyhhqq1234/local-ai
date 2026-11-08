#include "ops/linear/split/q4_q5/shapes/n5120_n5120_k4096/launch.h"

namespace ninfer::ops::detail::linear_split::q4_q5_n5120_n5120_k4096 {
namespace {
void launch(const Tensor& x, Weights weights, std::span<const Tensor> outputs, MemoryArena*,
            cudaStream_t stream) {
    // [9B 修复] 13..15（partial 尾块）会让 key/value 两段 NaN：15 及以下走已验证的 4 段独立路径。
    // 注：272 token（16×17，full 分支）也复现 NaN，但改成 ≤512 全走本路径后仍失败
    //     → 该 NaN 不在 attention 投影内，已回滚扩大阈值的改动（保留 ≤15 的原修复）。
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




