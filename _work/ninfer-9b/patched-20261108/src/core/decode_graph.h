#pragma once

#include <cuda_runtime.h>

#include <functional>

namespace ninfer {

// [9B 修复] 捕获期状态查询：捕获期间任何 host 同步（含默认流的 cudaStreamSynchronize）
// 都是 cudaErrorStreamCaptureUnsupported(error 900)，会让整个捕获 901 失效。
// 捕获体中所有工作只是被记录、不会真正执行，因此同步在捕获期语义上是空操作，可直接跳过。
[[nodiscard]] bool graph_capture_active() noexcept;

class DecodeGraphDefinition {
public:
    DecodeGraphDefinition() = default;
    ~DecodeGraphDefinition();

    DecodeGraphDefinition(const DecodeGraphDefinition&)            = delete;
    DecodeGraphDefinition& operator=(const DecodeGraphDefinition&) = delete;
    DecodeGraphDefinition(DecodeGraphDefinition&& other) noexcept;
    DecodeGraphDefinition& operator=(DecodeGraphDefinition&& other) noexcept;

    void capture(cudaStream_t stream, const std::function<void()>& body);
    [[nodiscard]] bool ready() const noexcept;
    void reset() noexcept;

private:
    friend class DecodeGraphCapture;
    friend class DecodeGraphExecutable;
    cudaGraph_t graph_ = nullptr;
};

// An unfinished capture is discarded on scope exit. All participating streams must
// rejoin the origin before finish(); the definition owns the resulting graph.
class DecodeGraphCapture {
public:
    explicit DecodeGraphCapture(cudaStream_t stream);
    ~DecodeGraphCapture();
    DecodeGraphCapture(const DecodeGraphCapture&)            = delete;
    DecodeGraphCapture& operator=(const DecodeGraphCapture&) = delete;

    [[nodiscard]] DecodeGraphDefinition finish();

private:
    cudaStream_t stream_;
};

class DecodeGraphExecutable {
public:
    DecodeGraphExecutable() = default;
    ~DecodeGraphExecutable();

    DecodeGraphExecutable(const DecodeGraphExecutable&)            = delete;
    DecodeGraphExecutable& operator=(const DecodeGraphExecutable&) = delete;
    DecodeGraphExecutable(DecodeGraphExecutable&& other) noexcept;
    DecodeGraphExecutable& operator=(DecodeGraphExecutable&& other) noexcept;

    void instantiate(const DecodeGraphDefinition& definition);
    void update(const DecodeGraphDefinition& definition);
    void upload(cudaStream_t stream);
    void launch(cudaStream_t stream);
    [[nodiscard]] bool ready() const noexcept;
    void reset() noexcept;

private:
    cudaGraphExec_t exec_ = nullptr;
};

} // namespace ninfer
