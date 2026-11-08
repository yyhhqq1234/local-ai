#include "ops/linear/swiglu/dispatch.h"
#include "ops/linear/swiglu/q4/launch.h"
#include "core/layout.h"
#include "ninfer/ops/silu_mul.h"

#include <array>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>

namespace ninfer::ops::detail {
namespace {
struct Plan {
    int last_tokens;
    LinearSwiGluLaunch launch;
    bool materialized = false;
};

constexpr std::array<Plan, 10> kPlans{{
    {1, launch_q4_swiglu_gemv_pair},
    {32, launch_q4_swiglu_small_t_tiled},
    {128, launch_q4_swiglu_materialized_projection, true},
    {168, launch_q4_swiglu_mma_split_half_pair_r32_c128_tail},
    {224, launch_q4_swiglu_materialized_projection, true},
    {256, launch_q4_swiglu_mma_split_half_pair_r32_c128},
    {384, launch_q4_swiglu_materialized_projection, true},
    {512, launch_q4_swiglu_mma_split_half_pair_r32_c128},
    {640, launch_q4_swiglu_materialized_projection, true},
    {std::numeric_limits<int>::max(), launch_q4_swiglu_mma_split_half_pair_r32_c128},
}};

const Plan& select_plan(int rows, int k, int tokens) {
    // 9B (H=4096)：gate+up 合并 24576 行
    const bool supported = (rows == 34816 && k == 5120) || (rows == 24576 && k == 4096);
    if (!supported || tokens <= 0)
        throw std::invalid_argument("q4 linear_swiglu: unsupported shape or token extent");
    // 9B (k=4096)：GEMV/small-t kernel 内硬编码了 27B 的中间维度，
    // 统一走 materialized projection（其 select_projection 全用运行期 K）
    if (k == 4096) {
        static const Plan kB9Plan{std::numeric_limits<int>::max(),
                                  launch_q4_swiglu_materialized_projection, true};
        return kB9Plan;
    }
    for (const auto& plan : kPlans)
        if (tokens <= plan.last_tokens) return plan;
    throw std::logic_error("q4 linear_swiglu: missing token route");
}

template <class Arena>
Tensor allocate_projection(Arena& arena, int tokens) {
    // 取两者较大值，保证 9B(24576) 与 27B(34816) 都能容纳（偏大安全）
    return arena.alloc(DType::BF16, {34816, tokens});
}

std::size_t materialized_bytes(int tokens) {
    WorkspaceLayoutBuilder layout;
    (void)allocate_projection(layout, tokens);
    return layout.peak_bytes(1);
}
} // namespace

std::size_t q4_linear_swiglu_capacity_workspace_bytes(int rows, int k, int first, int last) {
    if (first <= 0 || last < first)
        throw std::invalid_argument("q4 linear_swiglu: invalid token interval");
    (void)select_plan(rows, k, first);
    (void)select_plan(rows, k, last);
    std::size_t bytes = 0;
    int begin         = 1;
    for (const auto& plan : kPlans) {
        if (plan.materialized && plan.last_tokens >= first && begin <= last)
            bytes = std::max(bytes, materialized_bytes(std::min(plan.last_tokens, last)));
        if (plan.last_tokens >= last) break;
        begin = plan.last_tokens + 1;
    }
    return bytes;
}

void q4_linear_swiglu_dispatch(const Tensor& x, const Weight& w, Tensor& out,
                               MemoryArena& workspace, CudaExecutionView execution) {
    const auto& plan = select_plan(w.n, w.k, x.ne[1]);
    if (!plan.materialized) return plan.launch(x, w, out, execution.stream());
    auto scope   = workspace.scope();
    auto gate_up = allocate_projection(workspace, x.ne[1]);
    plan.launch(x, w, gate_up, execution.stream());
    if constexpr (false) {
        // [9B] 诊断关闭：cudaDeviceSynchronize 在 CUDA graph 捕获期是 error 900（非法），
        // 会让整个捕获 901 失效（分段探针实测：post.mlp_enter 仍 Active，进 swiglu 后作废）。
        // [9B 排障] launch 是异步的 —— 必须先同步再 dump，否则读到未写完的数据
        cudaDeviceSynchronize();
        const Tensor g = gate_up.slice(0, 0, out.ne[0]);
        const Tensor u = gate_up.slice(0, out.ne[0], out.ne[0]);
        std::FILE* pd = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/ptr-diag.txt", "a");
        if (pd) {
            std::fprintf(pd,
                         "[ptr] gate_up=%p rows=%d out=%p gate=%p up=%p "
                         "gu_nb1=%lld g_nb1=%lld contiguous=%d/%d\n",
                         gate_up.data, gate_up.ne[0], out.data, g.data, u.data,
                         static_cast<long long>(gate_up.nb[1]), static_cast<long long>(g.nb[1]),
                         g.is_contiguous() ? 1 : 0, u.is_contiguous() ? 1 : 0);
            std::fclose(pd);
        }
        // 同步后再 dump gate / up 的统计（保证读到的是 launch 的完整输出）
        auto dump_half = [](const Tensor& t, const char* tag) {
            const std::size_t cnt = static_cast<std::size_t>(t.ne[0]) * t.ne[1];
            if (cnt == 0 || cnt > 128u * 4096u) return;
            static unsigned short b[128 * 4096];
            cudaMemcpy(b, t.data, cnt * 2, cudaMemcpyDeviceToHost);
            int nan_c = 0; double s2 = 0.0; double mx = 0.0;
            for (std::size_t k = 0; k < cnt; ++k) {
                const unsigned short v = b[k];
                if ((v & 0x7fffu) == 0x7fffu) { ++nan_c; continue; }
                const int e = static_cast<int>((v >> 7) & 0xff) - 127;
                double frac = static_cast<double>(v & 0x7fu) / 128.0 + 1.0;
                if ((v & 0x7fu) == 0) frac = 1.0;
                const double val = std::ldexp(frac, e);
                s2 += val * val;
                if (val > mx) mx = val;
            }
            std::FILE* d = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/gateup.txt", "a");
            if (d) {
                std::fprintf(d, "%s n=%d T=%d nan=%d l2=%.4f max=%.4e bits=[%04x %04x %04x]\n",
                             tag, t.ne[0], t.ne[1], nan_c, std::sqrt(s2), mx, b[0], b[1], b[2]);
                std::fclose(d);
            }
        };
        dump_half(g, "gate");
        dump_half(u, "up  ");
    }
    silu_mul(gate_up.slice(0, 0, out.ne[0]), gate_up.slice(0, out.ne[0], out.ne[0]), out,
             execution);
    if constexpr (false) {
        // [9B] 诊断关闭：同上，捕获期非法同步
        // [9B 排障] 逐元素对比 gate/up/out 的原始 bits（找第一个不一致）
        cudaDeviceSynchronize();
        const Tensor g = gate_up.slice(0, 0, out.ne[0]);
        const Tensor u = gate_up.slice(0, out.ne[0], out.ne[0]);
        unsigned short hg[8] = {};
        unsigned short hu[8] = {};
        unsigned short ho[8] = {};
        cudaMemcpy(hg, g.data, sizeof(hg), cudaMemcpyDeviceToHost);
        cudaMemcpy(hu, u.data, sizeof(hu), cudaMemcpyDeviceToHost);
        cudaMemcpy(ho, out.data, sizeof(ho), cudaMemcpyDeviceToHost);
        // 同时取第 12288 行处（第二列起）的样本，验证列偏移
        unsigned short hg2[4] = {};
        unsigned short ho2[4] = {};
        cudaMemcpy(hg2, static_cast<const char*>(g.data) + g.nb[1], sizeof(hg2),
                   cudaMemcpyDeviceToHost);
        cudaMemcpy(ho2, static_cast<const char*>(out.data) + out.nb[1], sizeof(ho2),
                   cudaMemcpyDeviceToHost);
        std::FILE* d = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/elem.txt", "a");
        if (d) {
            std::fprintf(d, "[col0] gate=[%04x %04x %04x %04x %04x %04x %04x %04x]\n", hg[0],
                         hg[1], hg[2], hg[3], hg[4], hg[5], hg[6], hg[7]);
            std::fprintf(d, "[col0] up  =[%04x %04x %04x %04x %04x %04x %04x %04x]\n", hu[0],
                         hu[1], hu[2], hu[3], hu[4], hu[5], hu[6], hu[7]);
            std::fprintf(d, "[col0] out =[%04x %04x %04x %04x %04x %04x %04x %04x]\n", ho[0],
                         ho[1], ho[2], ho[3], ho[4], ho[5], ho[6], ho[7]);
            std::fprintf(d, "[col1] gate=[%04x %04x %04x %04x] out=[%04x %04x %04x %04x]\n",
                         hg2[0], hg2[1], hg2[2], hg2[3], ho2[0], ho2[1], ho2[2], ho2[3]);
            std::fclose(d);
        }
    }
}
} // namespace ninfer::ops::detail




