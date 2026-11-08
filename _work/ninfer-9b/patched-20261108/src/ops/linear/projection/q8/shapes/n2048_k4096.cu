#include "ops/linear/projection/q8/q8_shapes.h"
#include "ops/common/cuda/memory.cuh"
#include "ops/linear/kernels/q8/q8_instance_launch.cuh"

namespace ninfer::ops::detail {
namespace {
using Geometry = Q8N2048K4096;
using Access   = Q8ScaleAccess;
using Stage    = Q8ActivationStage;
using C4       = Q8A16SlicedKMmaSchedule<8, 16, 1, 1, Access::Direct, Cache::cg, Cache::cg,
                                         Stage::RuntimeActive>;
using C8       = Q8A16SlicedKMmaSchedule<8, 16, 1, 1, Access::Shared, Cache::ca, Cache::cg,
                                         Stage::RuntimeActive>;
using C40 =
    Q8A16SlicedKMmaSchedule<40, 8, 1, 2, Access::Shared, Cache::cg, Cache::cg, Stage::ActiveOnly>;
using C48 = Q8A16SlicedKMmaSchedule<48, 8, 1, 2, Access::Shared, Cache::ca, Cache::cg,
                                    Stage::RuntimeActive>;
using C56 =
    Q8A16SlicedKMmaSchedule<56, 8, 1, 2, Access::Shared, Cache::ca, Cache::cg, Stage::ActiveOnly>;
using C64 = Q8A16SlicedKMmaSchedule<64, 8, 1, 2, Access::Shared, Cache::ca, Cache::cg,
                                    Stage::RuntimeActive>;
} // namespace

Q8Launch select_q8_n2048_k4096(std::int32_t tokens) {
    if (tokens <= 4) return launch_q8_a16_sliced<Geometry, 4, C4>;
    if (tokens <= 8) return launch_q8_a16_sliced<Geometry, 8, C8>;
    if (tokens <= 32) return launch_q8_a16_sliced_r16_t16_w8_s2;
    if (tokens <= 40) return launch_q8_a16_sliced<Geometry, 40, C40>;
    if (tokens <= 48) return launch_q8_a16_sliced<Geometry, 48, C48>;
    if (tokens <= 56) return launch_q8_a16_sliced<Geometry, 56, C56>;
    if (tokens <= 64) return launch_q8_a16_sliced<Geometry, 64, C64>;
    if (tokens <= 128) return launch_q8_a16_sliced_r16_t16_w8_s2;
    if (tokens < 896) return launch_q8_a16_mma_r32_t128;
    return launch_q8_a16_mma_r64_t128;
}

// [9B/mtp] attention 四合一 (10240, 4096)：K 相同，直接复用 n2048_k4096 的 schedule。
Q8Launch select_q8_n10240_k4096(std::int32_t tokens) {
    return select_q8_n2048_k4096(tokens);
}
// [9B/mtp] (4096, 4096)：K 相同，复用 n2048_k4096 的 schedule。
Q8Launch select_q8_n4096_k4096(std::int32_t tokens) {
    return select_q8_n2048_k4096(tokens);
}
} // namespace ninfer::ops::detail
