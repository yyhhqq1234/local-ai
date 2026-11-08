#include "models/qwen3_5/execution/dense_mlp.h"

#include "core/layout.h"
#include "ninfer/ops/linear.h"
#include "ninfer/ops/linear_add.h"
#include "ninfer/ops/linear_swiglu.h"
#include "ninfer/ops/residual_add.h"
#include "ninfer/ops/silu_mul.h"

#include <cmath>
#include <cstdio>
#include <stdexcept>

namespace ninfer::models::qwen3_5::execution {

std::size_t dense_mlp_workspace_bytes(const DenseProfile& parameters, std::int32_t first,
                                      std::int32_t last, DenseMlpUse use) {
    if (first <= 0 || last < first) {
        throw std::invalid_argument("Dense MLP: invalid column interval");
    }
    const auto& gu   = parameters.gate_up;
    const auto& down = parameters.down;
    WorkspaceLayoutBuilder layout;
    if (use == DenseMlpUse::Mtp) {
        (void)layout.alloc(DType::BF16, {gu.n, last});
        {
            auto scope = layout.scope();
            (void)layout.alloc_bytes(ops::linear_workspace_capacity_bytes(
                gu.qtype, gu.n, gu.k, parameters.gate_up.policy, first, last));
        }
        (void)layout.alloc(DType::BF16, {gu.n / 2, last});
        (void)layout.alloc(DType::BF16, {down.n, last});
        (void)layout.alloc_bytes(ops::linear_workspace_capacity_bytes(
            down.qtype, down.n, down.k, parameters.down.policy, first, last));
    } else {
        (void)layout.alloc(DType::BF16, {gu.n / 2, last});
        {
            auto scope = layout.scope();
            (void)layout.alloc_bytes(ops::linear_swiglu_workspace_capacity_bytes(
                gu.qtype, gu.n, gu.k, parameters.gate_up.policy, first, last));
        }
        {
            auto scope = layout.scope();
            (void)layout.alloc_bytes(ops::linear_add_workspace_capacity_bytes(
                down.qtype, down.n, down.k, parameters.down.policy, first, last));
        }
    }
    return layout.peak_bytes(1);
}

void dense_mlp(const Tensor& hidden, const DenseParameters& parameters, Tensor& residual,
               DenseMlpUse use, MemoryArena& workspace, CudaExecutionView execution) {
    auto scope         = workspace.scope();
    const auto columns = hidden.ne[1];
    const auto& gu     = parameters.gate_up.weight;
    const auto& down   = parameters.down.weight;
    if (use == DenseMlpUse::Mtp) {
        Tensor gate_up = workspace.alloc(DType::BF16, {gu.n, columns});
        {
            auto call = workspace.scope();
            ops::linear(hidden, gu, gate_up, parameters.gate_up.policy, workspace, execution);
        }
        static int wdump = 0;
    if (wdump < 2) {
        ++wdump;
        std::FILE* wd = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/weight-diag.txt", "a");
        if (wd) {
            std::fprintf(wd,
                         "[gu] n=%d k=%d padded=[%d,%d] qtype=%d group=%d policy=%d\n"
                         "[down] n=%d k=%d padded=[%d,%d] qtype=%d group=%d policy=%d\n"
                         "[hidden] n=%d T=%d\n",
                         gu.n, gu.k, gu.padded_shape[0], gu.padded_shape[1], (int)gu.qtype, gu.group,
                         (int)parameters.gate_up.policy, down.n, down.k, down.padded_shape[0],
                         down.padded_shape[1], (int)down.qtype, down.group,
                         (int)parameters.down.policy, hidden.ne[0], columns);
            std::fclose(wd);
        }
    }
    Tensor activation = workspace.alloc(DType::BF16, {gu.n / 2, columns});
        ops::silu_mul(gate_up.slice(0, 0, gu.n / 2), gate_up.slice(0, gu.n / 2, gu.n / 2),
                      activation, execution);
        Tensor delta = workspace.alloc(DType::BF16, {down.n, columns});
        ops::linear(activation, down, delta, parameters.down.policy, workspace, execution);
        ops::residual_add(delta, residual, execution);
        return;
    }
    static int wdump = 0;
    if (wdump < 2) {
        ++wdump;
        std::FILE* wd = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/weight-diag.txt", "a");
        if (wd) {
            std::fprintf(wd,
                         "[gu] n=%d k=%d padded=[%d,%d] qtype=%d group=%d policy=%d\n"
                         "[down] n=%d k=%d padded=[%d,%d] qtype=%d group=%d policy=%d\n"
                         "[hidden] n=%d T=%d\n",
                         gu.n, gu.k, gu.padded_shape[0], gu.padded_shape[1], (int)gu.qtype, gu.group,
                         (int)parameters.gate_up.policy, down.n, down.k, down.padded_shape[0],
                         down.padded_shape[1], (int)down.qtype, down.group,
                         (int)parameters.down.policy, hidden.ne[0], columns);
            std::fclose(wd);
        }
    }
    Tensor activation = workspace.alloc(DType::BF16, {gu.n / 2, columns});
    {
        auto call = workspace.scope();
        ops::linear_swiglu(hidden, gu, activation, parameters.gate_up.policy, workspace, execution);
    }
    // [9B 排障] dump swiglu(activation) 与 down(delta) 的 l2 / nan
    // [9B] 诊断关闭：含 cudaDeviceSynchronize，会破坏 CUDA graph 捕获
    auto dump_tensor = [](const Tensor& t, const char* tag) {
        (void)t; (void)tag;
        return;  // [9B] 诊断关闭（见上）
        // [9B 排障] 必须先同步：上游 kernel 是异步的，直接 memcpy 会读到未写完的数据
        cudaDeviceSynchronize();
        const std::size_t cnt = static_cast<std::size_t>(t.ne[0]) * t.ne[1];
        if (cnt == 0 || cnt > 128u * 4096u) return;
        static unsigned short buf[128 * 4096];
        cudaMemcpy(buf, t.data, cnt * 2, cudaMemcpyDeviceToHost);
        int nan_c = 0; double sum2 = 0.0;
        for (std::size_t k = 0; k < cnt; ++k) {
            const unsigned short b = buf[k];
            if ((b & 0x7fffu) == 0x7fffu) { ++nan_c; continue; }
            const int e = static_cast<int>((b >> 7) & 0xff) - 127;
            double v = static_cast<double>(b & 0x7fu) / 128.0 + 1.0;
            if ((b & 0x7fu) == 0) v = 1.0;
            v = std::ldexp(v, e) * ((b >> 15) ? -1.0 : 1.0);
            sum2 += v * v;
        }
        std::FILE* d = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/mlp-diag.txt", "a");
        if (d) {
            std::fprintf(d, "%s n=%d T=%d nan=%d l2=%.4f bits=[%04x %04x %04x %04x %04x %04x]\n",
                         tag, t.ne[0], t.ne[1], nan_c, std::sqrt(sum2), buf[0], buf[1], buf[2],
                         buf[3], buf[4], buf[5]);
            std::fclose(d);
        }
    };
    {
        // [9B 排障] 打印张量 device 指针，检查 activation 与 gate_up 是否 alias
        std::FILE* pd = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/ptr-diag.txt", "a");
        if (pd) {
            std::fprintf(pd,
                         "[ptr] activation=%p (%zu B) hidden=%p (%zu B) delta=%zu B\n",
                         activation.data,
                         static_cast<std::size_t>(activation.ne[0]) * activation.ne[1] * 2,
                         hidden.data, static_cast<std::size_t>(hidden.ne[0]) * hidden.ne[1] * 2,
                         static_cast<std::size_t>(down.n) * columns * 2);
            std::fclose(pd);
        }
    }
    dump_tensor(activation, "swiglu");
    dump_tensor(residual, "residual(pre)");
    // [9B 修复] ops::linear_add 的 sliced-K 与 LinearResidualAddEpilogue 组合是 no-op：
    // for_each_token_slice(9, kTokenCapacity=2) 分 5 批，每批都读-改-写同一 residual 地址，
    // 多批互相覆盖后净效果为零（bit 级实测 residual(pre)==residual(post)）。
    // 拆成「纯投影 + 单独 residual_add」两段，语义等价且避开该路径。
    {
        Tensor delta = workspace.alloc(DType::BF16, {down.n, columns});
        {
            auto call = workspace.scope();
            ops::linear(activation, down, delta, parameters.down.policy, workspace, execution);
        }
        // [9B 排障] 确认 delta 是否真的被 linear 写入（层2+ 若全 0 → workspace 复用踩踏）
        // [9B] 诊断关闭：cudaDeviceSynchronize 在 CUDA graph 捕获期内是 error 900（非法），
        //      会让整个捕获 901 失效（sanitizer 实测定位）。
        if constexpr (false) {
            cudaDeviceSynchronize();
            unsigned short probe[6] = {};
            cudaMemcpy(probe, delta.data, sizeof(probe), cudaMemcpyDeviceToHost);
            std::FILE* dd = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/delta-diag.txt", "a");
            if (dd) {
                std::fprintf(dd,
                             "[delta] ptr=%p residual=%p same=%d bits=[%04x %04x %04x %04x %04x %04x]\n",
                             delta.data, residual.data, delta.data == residual.data ? 1 : 0,
                             probe[0], probe[1], probe[2], probe[3], probe[4], probe[5]);
                std::fclose(dd);
            }
        }
        ops::residual_add(delta, residual, execution);
    }
    dump_tensor(residual, "residual(post)");
}

} // namespace ninfer::models::qwen3_5::execution






