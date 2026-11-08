#include "models/qwen3_5/program/program_impl.h"
#include <cstdio>
#include <vector>
#include "core/device.h"

namespace ninfer::models::qwen3_5::detail {

ops::SamplingMask ProgramImpl::bind_grammar_mask(runtime::TokenMaskProvider* provider,
                                                 std::size_t row) {
    grammar_dead_positions[row] = 0;
    if (!provider || !provider->constrained(row)) { return {}; }
    const auto words = grammar_masks_device.ne[0];
    auto* device_words =
        static_cast<const std::uint32_t*>(grammar_masks_device.data) + row * (draft_window + 1) * words;
    // [9B 修复] decode 路径直接绑定 device 行，原先没有任何内容检查。
    // 实测带 tools 请求时该行全 0 → 采样整行 -inf → 取到非法 id → U+FFFD / 正文空
    // （去掉 trap 后不再崩，但内容无效）。这里做一次全 0 检查（≈31KB/请求），
    // 全 0 则降级为「不加约束」，让对话按普通文本继续。
    {
        static thread_local std::vector<std::uint32_t> probe;
        probe.resize(static_cast<std::size_t>(words));
        CUDA_CHECK(cudaMemcpy(probe.data(), device_words,
                              static_cast<std::size_t>(words) * sizeof(std::uint32_t),
                              cudaMemcpyDeviceToHost));
        bool any_allowed = false;
        for (const auto v : probe) {
            if (v != 0u) { any_allowed = true; break; }
        }
        if (!any_allowed) {
            std::fprintf(stderr, "[grammar] row %zu mask is empty -> unconstrained\n", row);
            return {};
        }
    }
    return {device_words, words};
}

ops::SamplingMask ProgramImpl::fill_grammar_mask(runtime::TokenMaskProvider* provider,
                                                 std::size_t row, std::span<const TokenId> drafts) {
    grammar_dead_positions[row] = 0;
    if (!provider || !provider->constrained(row)) { return {}; }
    const auto words  = static_cast<std::size_t>(grammar_masks_device.ne[0]);
    const auto offset = row * (draft_window + 1) * words;
    std::span<std::uint32_t> host(static_cast<std::uint32_t*>(grammar_masks_host->data()) + offset,
                                  (drafts.size() + 1) * words);
    grammar_dead_positions[row] = provider->fill(row, drafts, host);
    // [9B 修复] 语法不可满足（整行掩码全 0 = 无任何合法 token）时，不把「全掩」下发给采样器，
    // 而是降级为“不加约束”，让请求按普通文本继续生成。
    // 原来全掩会让采样归约得 -inf → 旧代码直接 device trap 打死进程，
    // 现在 trap 已去掉，但请求会以 "selected token violates the request grammar" 500 收场；
    // DSH 每轮都带 tools 字段，因此必须降级而不是失败。
    bool any_allowed = false;
    for (std::size_t i = 0; i < host.size(); ++i) {
        if (host[i] != 0u) { any_allowed = true; break; }
    }
    if (!any_allowed) { return {}; }
    auto* device_words          = static_cast<std::uint32_t*>(grammar_masks_device.data) + offset;
    CUDA_CHECK(cudaMemcpyAsync(device_words, host.data(), host.size_bytes(), cudaMemcpyHostToDevice,
                               device.stream()));
    provider->uploaded(row, host.size_bytes());
    return {device_words, static_cast<std::int32_t>(words)};
}

} // namespace ninfer::models::qwen3_5::detail
