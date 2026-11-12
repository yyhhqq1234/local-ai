// bw_probe.cu — 显存有效带宽实测（决定 100 tok/s 是否够得着的那个数）
// 编译（Windows, MSVC BuildTools + CUDA 13.0）:
//   call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvarsall.bat" x64
//   nvcc -O3 -arch=sm_120a bw_probe.cu -o bw_probe.exe
// 运行:
//   bw_probe.exe            # 默认 1024 MiB 缓冲, 100 轮, vectorized float4
#include <cstdio>
#include <cuda_runtime.h>

__global__ void read_kernel(const float4* __restrict__ in, float* __restrict__ out, size_t n4)
{
    size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x;
    size_t stride = (size_t)gridDim.x * blockDim.x;
    float4 acc = make_float4(0.f, 0.f, 0.f, 0.f);
    for (; i < n4; i += stride) {
        float4 v = in[i];
        acc.x += v.x; acc.y += v.y; acc.z += v.z; acc.w += v.w;
    }
    if ((acc.x + acc.y + acc.z + acc.w) == 12345.f) out[0] = acc.x;  // 防消除
}

__global__ void write_kernel(float4* __restrict__ out, size_t n4)
{
    size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x;
    size_t stride = (size_t)gridDim.x * blockDim.x;
    float4 v = make_float4(1.f, 2.f, 3.f, 4.f);
    for (; i < n4; i += stride) out[i] = v;
}

int main()
{
    int dev = 0, ms = 0;
    cudaDeviceProp prop;
    cudaGetDevice(&dev);
    cudaGetDeviceProperties(&prop, dev);
    cudaDeviceGetAttribute(&ms, cudaDevAttrMemoryClockRate, dev);      // kHz
    int bus = 0;
    cudaDeviceGetAttribute(&bus, cudaDevAttrGlobalMemoryBusWidth, dev);
    size_t total = prop.totalGlobalMem;

    const size_t MB = 1024ull * 1024ull;
    const size_t bytes = 1024 * MB;
    const int iters = 100;
    void* p = nullptr;
    if (cudaMalloc(&p, bytes) != cudaSuccess) { printf("cudaMalloc failed\n"); return 1; }
    cudaMemset(p, 0, bytes);

    size_t n4 = bytes / sizeof(float4);
    float* scratch = nullptr;
    cudaMalloc(&scratch, 4096);

    // read
    cudaEvent_t a, b; cudaEventCreate(&a); cudaEventCreate(&b);
    read_kernel<<<2048, 256>>>((const float4*)p, scratch, n4);
    cudaDeviceSynchronize();
    cudaEventRecord(a);
    for (int i = 0; i < iters; ++i) read_kernel<<<2048, 256>>>((const float4*)p, scratch, n4);
    cudaEventRecord(b); cudaDeviceSynchronize();
    float rms = 0.f; cudaEventElapsedTime(&rms, a, b);
    double rd = (double)bytes * iters / (rms * 1e6);

    cudaEventRecord(a);
    for (int i = 0; i < iters; ++i) write_kernel<<<2048, 256>>>((float4*)p, n4);
    cudaEventRecord(b); cudaDeviceSynchronize();
    float wms = 0.f; cudaEventElapsedTime(&wms, a, b);
    double wr = (double)bytes * iters / (wms * 1e6);

    printf("GPU        : %s\n", prop.name);
    printf("VRAM       : %.2f GiB total\n", (double)total / 1073741824.0);
    printf("mem clock  : %.0f MHz   bus width: %d bit\n", ms / 1000.0, bus);
    printf("theoretical: %.1f GB/s (bus*clock*2/8)\n", (double)bus * (ms / 1000.0) * 1e6 * 2.0 / 8.0 / 1e9);
    printf("read  BW   : %.1f GB/s   (%.1f%% of theoretical)\n", rd, rd / ((double)bus * (ms / 1000.0) * 1e6 * 2.0 / 8.0 / 1e9) * 100.0);
    printf("write BW   : %.1f GB/s\n", wr);
    cudaFree(scratch); cudaFree(p);
    return 0;
}
