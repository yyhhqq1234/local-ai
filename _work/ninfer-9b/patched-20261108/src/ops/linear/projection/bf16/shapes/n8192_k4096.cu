#include "ops/linear/projection/bf16/bf16_shapes.h"
#include "ops/common/cuda/memory.cuh"
#include "ops/linear/projection/bf16/bf16_launch.cuh"

namespace ninfer::ops::detail {
namespace {
using S0 = Bf16ScheduleInstance<
    Bf16A16GemvSchedule<4, 1, 2, 16, 4, Bf16ActivationAccess::Direct, Bf16WeightCache::Default,
                        Bf16PhaseOrder::Sequential, 1, 1, 4, 2>,
    4096>;
using S1 = Bf16ScheduleInstance<Bf16A16SlicedKMmaSchedule<16, 8, 4, 64, 3>, 4096>;
using S2 = Bf16ScheduleInstance<Bf16A16SlicedKMmaSchedule<32, 8, 4, 64, 2>, 4096>;
using S3 = Bf16ScheduleInstance<Bf16A16SlicedKMmaSchedule<32, 24, 4, 64, 2>, 4096>;
using S4 = Bf16ScheduleInstance<
    Bf16A16MmaSchedule<32, 32, 256, 16, 16, 3, 1, Cache::cg, Cache::cg,
                       Bf16MmaFragmentPipeline::PingPong, Bf16MmaRaster::TokenFast>,
    4096>;
using S5 = Bf16ScheduleInstance<Bf16A16TmaMmaSchedule<64, 32, 64, 16, 8, 3, 1>, 4096>;
using S6 = Bf16ScheduleInstance<
    Bf16A16MmaSchedule<64, 32, 128, 32, 16, 2, 2, Cache::cg, Cache::cg,
                       Bf16MmaFragmentPipeline::PingPong, Bf16MmaRaster::TokenFast>,
    4096>;
using S7 = Bf16ScheduleInstance<
    Bf16A16TmaMmaSchedule<128, 64, 64, 32, 32, 2, 2, Bf16MmaRaster::TokenFast, 1>, 4096>;
using S8 = Bf16ScheduleInstance<Bf16A16TmaMmaSchedule<128, 128, 64, 64, 32, 3, 1>, 4096>;
using S9 = Bf16ScheduleInstance<
    Bf16A16TmaMmaSchedule<128, 64, 64, 64, 32, 2, 2, Bf16MmaRaster::RowFast, 1>, 4096>;
} // namespace

Bf16Launch select_bf16_n8192_k4096(std::int32_t tokens) {
    if (tokens <= 1) return launch_bf16_gemv<S0>;
    if (tokens <= 8) return launch_bf16_sliced_k_mma<S1>;
    if (tokens <= 32) return launch_bf16_sliced_k_mma<S2>;
    if (tokens <= 48) return launch_bf16_sliced_k_mma<S3>;
    if (tokens <= 64) return launch_bf16_mma<S4>;
    if (tokens <= 96) return launch_bf16_tma_mma<S5>;
    if (tokens <= 128) return launch_bf16_mma<S6>;
    if (tokens <= 512) return launch_bf16_tma_mma<S7>;
    if (tokens <= 2048) return launch_bf16_tma_mma<S8>;
    return launch_bf16_tma_mma<S9>;
}
Bf16Launch select_bf16_n10240_k4096(std::int32_t tokens) {
    return select_bf16_n8192_k4096(tokens);
}

// [9B] mtp/input_projection (4096, 8192)：K=8192，按 n8192_k4096 的档位同构生成。
using T0 = Bf16ScheduleInstance<
    Bf16A16GemvSchedule<4, 1, 2, 16, 4, Bf16ActivationAccess::Direct, Bf16WeightCache::Default,
                        Bf16PhaseOrder::Sequential, 1, 1, 4, 2>,
    8192>;
using T1 = Bf16ScheduleInstance<Bf16A16SlicedKMmaSchedule<16, 8, 4, 64, 3>, 8192>;
using T2 = Bf16ScheduleInstance<Bf16A16SlicedKMmaSchedule<32, 8, 4, 64, 2>, 8192>;
using T3 = Bf16ScheduleInstance<Bf16A16SlicedKMmaSchedule<32, 24, 4, 64, 2>, 8192>;
using T4 = Bf16ScheduleInstance<
    Bf16A16MmaSchedule<32, 32, 256, 16, 16, 3, 1, Cache::cg, Cache::cg,
                       Bf16MmaFragmentPipeline::PingPong, Bf16MmaRaster::TokenFast>,
    8192>;
using T5 = Bf16ScheduleInstance<Bf16A16TmaMmaSchedule<64, 32, 64, 16, 8, 3, 1>, 8192>;
using T6 = Bf16ScheduleInstance<
    Bf16A16MmaSchedule<64, 32, 128, 32, 16, 2, 2, Cache::cg, Cache::cg,
                       Bf16MmaFragmentPipeline::PingPong, Bf16MmaRaster::TokenFast>,
    8192>;
using T7 = Bf16ScheduleInstance<
    Bf16A16TmaMmaSchedule<128, 64, 64, 32, 32, 2, 2, Bf16MmaRaster::TokenFast, 1>, 8192>;
using T8 = Bf16ScheduleInstance<Bf16A16TmaMmaSchedule<128, 128, 64, 64, 32, 3, 1>, 8192>;
using T9 = Bf16ScheduleInstance<
    Bf16A16TmaMmaSchedule<128, 64, 64, 64, 32, 2, 2, Bf16MmaRaster::RowFast, 1>, 8192>;

Bf16Launch select_bf16_n4096_k8192(std::int32_t tokens) {
    if (tokens <= 1) return launch_bf16_gemv<T0>;
    if (tokens <= 8) return launch_bf16_sliced_k_mma<T1>;
    if (tokens <= 32) return launch_bf16_sliced_k_mma<T2>;
    if (tokens <= 48) return launch_bf16_sliced_k_mma<T3>;
    if (tokens <= 64) return launch_bf16_mma<T4>;
    if (tokens <= 96) return launch_bf16_tma_mma<T5>;
    if (tokens <= 128) return launch_bf16_mma<T6>;
    if (tokens <= 512) return launch_bf16_tma_mma<T7>;
    if (tokens <= 2048) return launch_bf16_tma_mma<T8>;
    return launch_bf16_tma_mma<T9>;
}
} // namespace ninfer::ops::detail
