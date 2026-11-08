#include "ops/softmax_attention/dense/causal_cache/bf16/launch.h"
#include "ops/softmax_attention/kernels/causal/bf16/template_launch.cuh"
#include "ops/softmax_attention/dense/causal_cache/bf16/plan.h"
#include <cstdio>

namespace ninfer::ops::detail {
// [9B 排障] 诊断开关：功能修好后置 false（原为 true），避免每次调用同步+fopen 落盘。
constexpr bool kKvDiag = false;
__device__ unsigned long long g_kv_write_hits      = 0ULL;
__device__ long long          g_kv_write_first_dst = -1;
__device__ long long          g_kv_write_first_src = -1;
__device__ unsigned int       g_kv_write_first_value = 0;
__device__ int                g_kv_write_page        = -1;
__device__ int                g_kv_write_key         = -1;
__device__ int                g_kv_write_block       = -1;
__device__ int                g_kv_write_start       = -1;
__device__ int                g_kv_write_stop        = -1;
// 非模板 host 诊断实现：模板函数内的 stdio 在 nvcc 下会被当作 device 代码剥离，
// 所以把落盘动作放在这里（普通 host 函数，已验证 fopen 可用）。
void bf16_kv_diag_write(const char* tag, int hd_g, int q_g, int kv_g, int hd_p, int q_p,
                        int hd_c, int kv_c, int w, int b, int stride, int vis, int vc, int tr,
                        int bits) {
    std::FILE* d = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/kv-which.txt", "a");
    if (!d) return;
    std::fprintf(d,
                 "%s bits=%d geom(hd=%d,q=%d,kv=%d) p(hd=%d,q=%d) cache(hd=%d,kv=%d) "
                 "w=%d b=%d stride=%d vis=%d vc=%d tr=%d\n",
                 tag, bits, hd_g, q_g, kv_g, hd_p, q_p, hd_c, kv_c, w, b, stride, vis, vc, tr);
    std::fclose(d);
}
namespace {

template <class G, Bf16KvInstance Instance, bool Writable, class Input>
void grouped(const CausalAttentionOperands& p, Bf16KvCacheView<Writable> cache, Input input,
             const Bf16KvCausalPlan& plan, CausalPartialView partial, cudaStream_t stream) {
    using S           = typename Bf16KvInstanceTraits<Instance>::Schedule;
    const auto invoke = [&]<bool MultiBatch, bool Masked>() {
        launch_bf16_kv_grouped_mma<G, S, MultiBatch, Masked>(p, cache, input, plan.partition,
                                                             partial, stream);
        launch_bf16_kv_merge<G, Bf16KvMergeSchedule<256>, MultiBatch, Masked>(
            p, cache, plan.partition, partial, stream);
    };
    if (p.batch == 1) {
        if (cache.valid_columns)
            invoke.template operator()<false, true>();
        else
            invoke.template operator()<false, false>();
    } else {
        if (cache.valid_columns)
            invoke.template operator()<true, true>();
        else
            invoke.template operator()<true, false>();
    }
}

template <class G, bool Writable, class Input>
void grouped_instance(const CausalAttentionOperands& p, Bf16KvCacheView<Writable> cache,
                      Input input, const Bf16KvCausalPlan& plan, CausalPartialView partial,
                      cudaStream_t stream) {
    switch (plan.instance) {
    case Bf16KvInstance::GroupedDecode:
        return grouped<G, Bf16KvInstance::GroupedDecode>(p, cache, input, plan, partial, stream);
    case Bf16KvInstance::Grouped32:
        return grouped<G, Bf16KvInstance::Grouped32>(p, cache, input, plan, partial, stream);
    case Bf16KvInstance::Grouped64:
        return grouped<G, Bf16KvInstance::Grouped64>(p, cache, input, plan, partial, stream);
    default:
        throw std::logic_error("BF16 grouped launch received a tiled plan");
    }
}

void tiled(const CausalAttentionOperands& p, Bf16KvReadView cache, const Bf16KvCausalPlan& plan,
           cudaStream_t stream) {
    const auto invoke = [&]<class G>() {
        if (plan.instance == Bf16KvInstance::Tiled128)
            launch_bf16_kv_tiled_mma<
                G, typename Bf16KvInstanceTraits<Bf16KvInstance::Tiled128>::Schedule>(p, cache,
                                                                                      stream);
        else
            launch_bf16_kv_tiled_mma<
                G, typename Bf16KvInstanceTraits<Bf16KvInstance::Tiled64>::Schedule>(p, cache,
                                                                                     stream);
    };
    if (p.query_heads == 24)
        invoke.template operator()<CausalD256H24Kv4>();
    else if (p.query_heads == 16 && cache.kv_heads == 4)
        invoke.template operator()<CausalD256H16Kv4>();   // 9B
    else
        invoke.template operator()<CausalD256H16Kv2>();
}

template <class Input>
void execute_grouped(const Tensor& q, Input input, const Tensor& positions, float scale,
                     PagedKVBatchLayerView cache, const Tensor* valid, const Tensor* rows,
                     const Bf16KvCausalPlan& plan, MemoryArena& workspace, Tensor& out,
                     cudaStream_t stream) {
    auto scope   = workspace.scope();
    auto storage = allocate_causal_partials(workspace, plan.query_heads, plan.width,
                                            plan.partition.capacity, plan.batch);
    const auto p = make_causal_operands(q, positions, out, scale, plan.envelope.max_visible_keys);
    const auto view    = bf16_kv_cache_view<Input::writes_cache>(cache, valid, rows);
    const auto partial = storage.view();
    if (p.query_heads == 24)
        grouped_instance<CausalD256H24Kv4>(p, view, input, plan, partial, stream);
    else if (p.query_heads == 16 && view.kv_heads == 4)
        grouped_instance<CausalD256H16Kv4>(p, view, input, plan, partial, stream);   // 9B
    else
        grouped_instance<CausalD256H16Kv2>(p, view, input, plan, partial, stream);
}
} // namespace

void bf16_kv_append_attention(const Tensor& q, const Tensor& k, const Tensor& v,
                              const Tensor& positions, const Tensor& valid_columns,
                              const Tensor& table_rows, float scale, PagedKVBatchLayerView cache,
                              CausalAttentionExecutionEnvelope envelope, MemoryArena& workspace,
                              Tensor& out, CudaExecutionView execution) {
    const cudaStream_t stream = execution.stream();
    if constexpr (kKvDiag) {
        std::FILE* diag = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/kv-entry.txt", "a");
        if (diag) {
            const int w = q.ne[2];
            int p0 = -1, pL = -1, rowsel = -1, tab0 = -1, tab1 = -1, nanw = -1;
            if (w >= 1 && w <= 4096 && positions.data != nullptr) {
                cudaDeviceSynchronize();
                cudaMemcpy(&p0, positions.data, sizeof(int), cudaMemcpyDeviceToHost);
                cudaMemcpy(&pL, static_cast<const char*>(positions.data) +
                                    static_cast<std::size_t>(w - 1) * sizeof(int),
                           sizeof(int), cudaMemcpyDeviceToHost);
                if (table_rows.data != nullptr) {
                    cudaMemcpy(&rowsel, table_rows.data, sizeof(int), cudaMemcpyDeviceToHost);
                }
                const int logical_pages = static_cast<int>(cache.block_tables.ne[0]);
                const int rows          = static_cast<int>(cache.block_tables.ne[1]);
                const int use_row       = rowsel > 0 ? rowsel : 0;
                if (logical_pages > 0 && rows > 0) {
                    const std::size_t base = static_cast<std::size_t>(use_row) * logical_pages;
                    cudaMemcpy(&tab0,
                               static_cast<const char*>(cache.block_tables.data) +
                                   base * sizeof(int),
                               sizeof(int), cudaMemcpyDeviceToHost);
                    if (logical_pages > 1) {
                        cudaMemcpy(&tab1,
                                   static_cast<const char*>(cache.block_tables.data) +
                                       (base + 1) * sizeof(int),
                                   sizeof(int), cudaMemcpyDeviceToHost);
                    }
                }
                const int lead = static_cast<int>(cache.k_pages.ne[0]);
                const int psz  = static_cast<int>(cache.k_pages.ne[1]);
                const int kvh  = static_cast<int>(cache.k_pages.ne[2]);
                nanw           = 0;
                const int probes[4] = {0, 1, pL > 0 ? pL - 1 : 0, pL};
                for (int j = 0; j < 4; ++j) {
                    const int p = probes[j];
                    if (p < 0 || p > pL || p >= 64) continue;
                    const int page = tab0;
                    const int row  = p & 63;
                    const long long idx = static_cast<long long>(lead) * row +
                                          static_cast<long long>(lead) * psz * kvh * page;
                    unsigned short v4[4] = {};
                    cudaMemcpy(v4, static_cast<const char*>(cache.k_pages.data) + idx * 2, 8,
                               cudaMemcpyDeviceToHost);
                    for (int i = 0; i < 4; ++i)
                        if ((v4[i] & 0x7fffu) == 0x7fffu) ++nanw;
                }
            }
            std::fprintf(diag, "[append] q=%d kv=%d w=%d b=%d p0=%d pL=%d row=%d tab=%d,%d nan=%d%c",
                         q.ne[1], cache.num_kv_heads, w, q.ne[3], p0, pL, rowsel, tab0, tab1, nanw,
                         static_cast<char>(10));
            std::fclose(diag);
        }
    }
    if constexpr (kKvDiag) {
        const unsigned long long zero_hits = 0ULL;
        const long long minus_one          = -1;
        cudaMemcpyToSymbol(g_kv_write_hits, &zero_hits, sizeof(zero_hits));
        cudaMemcpyToSymbol(g_kv_write_first_dst, &minus_one, sizeof(minus_one));
        cudaMemcpyToSymbol(g_kv_write_first_src, &minus_one, sizeof(minus_one));
    }
    const auto plan = select_bf16_kv_causal_plan(q.ne[1], cache.num_kv_heads, q.ne[2], q.ne[3],
                                                 envelope, execution.multiprocessor_count());
    if (!plan.grouped()) {
        kv::launch_paged_write(select_bf16_kv_write(k.ne[1]), k, v, positions, valid_columns,
                               table_rows, cache, stream);
        tiled(make_causal_operands(q, positions, out, scale, envelope.max_visible_keys),
              bf16_kv_cache_view<false>(cache, &valid_columns, &table_rows), plan, stream);
    } else {
        execute_grouped(q,
                        CausalAppendInput{static_cast<const __nv_bfloat16*>(k.data),
                                          static_cast<const __nv_bfloat16*>(v.data)},
                        positions, scale, cache, &valid_columns, &table_rows, plan, workspace, out,
                        stream);
    }
    if constexpr (kKvDiag) {
        std::FILE* d9 = std::fopen("D:/BaiduNetdiskDownload/Local-AI/_tools/kv-post.txt", "a");
        if (d9) {
            const int w = q.ne[2];
            int pL = -1, tab0 = 0, rowsel = -1, valid0 = -1;
            int nanh[4] = {0, 0, 0, 0};
            char map[80];
            map[0]  = 0;
            int nn  = -1;
            if (w >= 1 && positions.data != nullptr) {
                cudaDeviceSynchronize();
                cudaMemcpy(&pL,
                           static_cast<const char*>(positions.data) +
                               static_cast<std::size_t>(w - 1) * sizeof(int),
                           sizeof(int), cudaMemcpyDeviceToHost);
                if (table_rows.data != nullptr) {
                    cudaMemcpy(&rowsel, table_rows.data, sizeof(int), cudaMemcpyDeviceToHost);
                }
                if (valid_columns.data != nullptr) {
                    cudaMemcpy(&valid0, valid_columns.data, sizeof(int), cudaMemcpyDeviceToHost);
                }
                const int logp    = static_cast<int>(cache.block_tables.ne[0]);
                const int use_row = rowsel > 0 ? rowsel : 0;
                if (logp > 0) {
                    cudaMemcpy(&tab0,
                               static_cast<const char*>(cache.block_tables.data) +
                                   static_cast<std::size_t>(use_row) * logp * sizeof(int),
                               sizeof(int), cudaMemcpyDeviceToHost);
                }
                const int lead = static_cast<int>(cache.k_pages.ne[0]);
                const int psz  = static_cast<int>(cache.k_pages.ne[1]);
                const int kvh  = static_cast<int>(cache.k_pages.ne[2]);
                nn             = 0;
                for (int head = 0; head < kvh && head < 4; ++head) {
                    for (int p = 0; p <= pL && p < 64; ++p) {
                        const int row       = p & 63;
                        const long long idx = static_cast<long long>(lead) * psz *
                                                  (head + static_cast<long long>(kvh) * tab0) +
                                              static_cast<long long>(lead) * row;
                        unsigned short v4[4] = {};
                        cudaMemcpy(v4, static_cast<const char*>(cache.k_pages.data) + idx * 2, 8,
                                   cudaMemcpyDeviceToHost);
                        const bool isn = (v4[0] & 0x7fffu) == 0x7fffu;
                        if (isn) ++nanh[head];
                        if (head == 0) {
                            map[p] = isn ? 'N' : '.';
                            if (isn) ++nn;
                        }
                    }
                }
                map[(pL >= 0 && pL < 79) ? pL + 1 : 0] = 0;
            }
            unsigned long long hits = 0;
            long long fdst = -1, fsrc = -1;
            unsigned int fval = 0;
            int wpage = -1, wkey = -1, wblock = -1, wstart = -1, wstop = -1;
            cudaMemcpyFromSymbol(&hits, g_kv_write_hits, sizeof(hits));
            cudaMemcpyFromSymbol(&fdst, g_kv_write_first_dst, sizeof(fdst));
            cudaMemcpyFromSymbol(&fsrc, g_kv_write_first_src, sizeof(fsrc));
            cudaMemcpyFromSymbol(&fval, g_kv_write_first_value, sizeof(fval));
            cudaMemcpyFromSymbol(&wpage, g_kv_write_page, sizeof(wpage));
            cudaMemcpyFromSymbol(&wkey, g_kv_write_key, sizeof(wkey));
            cudaMemcpyFromSymbol(&wblock, g_kv_write_block, sizeof(wblock));
            cudaMemcpyFromSymbol(&wstart, g_kv_write_start, sizeof(wstart));
            cudaMemcpyFromSymbol(&wstop, g_kv_write_stop, sizeof(wstop));
            std::fprintf(d9, "[post] w=%d pL=%d row=%d tab0=%d valid=%d nan=%d nanh=%d,%d,%d,%d hits=%llu fdst=%lld fsrc=%lld fval=%04x wpage=%d wkey=%d wblk=%d wrange=%d..%d map=%s%c",
                         w, pL, rowsel, tab0, valid0, nn, nanh[0], nanh[1], nanh[2], nanh[3], hits,
                         fdst, fsrc, fval, wpage, wkey, wblock, wstart, wstop, map,
                         static_cast<char>(10));
            std::fclose(d9);
        }
    }
}

void bf16_kv_cached_attention(const Tensor& q, const Tensor& positions, float scale,
                              const PagedKVLayerView& cache,
                              CausalAttentionExecutionEnvelope envelope, MemoryArena& workspace,
                              Tensor& out, CudaExecutionView execution) {
    const cudaStream_t stream = execution.stream();
    const auto plan = select_bf16_kv_causal_plan(q.ne[1], cache.num_kv_heads, q.ne[2], 1, envelope,
                                                 execution.multiprocessor_count());
    const auto view = single_row_paged_kv_batch_view(cache);
    if (!plan.grouped()) {
        tiled(make_causal_operands(q, positions, out, scale, envelope.max_visible_keys),
              bf16_kv_cache_view<false>(view), plan, stream);
    } else {
        execute_grouped(q, CausalCachedInput{}, positions, scale, view, nullptr, nullptr, plan,
                        workspace, out, stream);
    }
}
} // namespace ninfer::ops::detail





