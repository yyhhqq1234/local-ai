// 独立测试：验证 WIC 图片解码与 WinHTTP 下载（不经过引擎，绕开模型加载卡点）
// 编译：cl /std:c++20 /utf-8 /EHsc /I<include> test_media_win.cpp decode_win.cpp acquire_win.cpp
//      windowscodecs.lib ole32.lib winhttp.lib

#include "media/decode/decode.h"
#include "product/media_acquire/acquire.h"

#include <cstdio>
#include <fstream>
#include <string>
#include <vector>

namespace {

std::vector<std::uint8_t> slurp(const char* path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    return {std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>()};
}

// 生成一个 2x2 的最小 PNG（用于无外部素材时自测）
std::vector<std::uint8_t> tiny_png() {
    // 2x2 RGB PNG，红/绿/蓝/白
    static const unsigned char png[] = {
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D,
        0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x02,
        0x08, 0x02, 0x00, 0x00, 0x00, 0xFD, 0xD4, 0x9A, 0x73, 0x00, 0x00, 0x00,
        0x16, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0xF8, 0xCF, 0xC0, 0xF0,
        0x9F, 0x81, 0x81, 0x01, 0x03, 0x0C, 0x0C, 0x0C, 0x0C, 0x00, 0x00, 0x0E,
        0xFB, 0x02, 0xFE, 0xA8, 0x4A, 0x53, 0x69, 0x00, 0x00, 0x00, 0x00, 0x49,
        0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82};
    return {std::begin(png), std::end(png)};
}

void test_image() {
    using namespace ninfer::media;
    std::printf("[TEST] decode_image (WIC)\n");
    try {
        const auto bytes = tiny_png();
        const auto info  = decode::inspect_image(bytes, {});
        std::printf("  inspect: %dx%d\n", info.width, info.height);
        const auto image = decode::decode_image(bytes, {});
        std::printf("  decode : %dx%d, rgb bytes = %zu (expect %d)\n", image.width, image.height,
                    image.rgb.size(), image.width * image.height * 3);
        if (image.width == 2 && image.height == 2 && image.rgb.size() == 12) {
            std::printf("  RESULT: PASS\n");
        } else {
            std::printf("  RESULT: FAIL (unexpected dimensions)\n");
        }
    } catch (const std::exception& e) {
        std::printf("  RESULT: FAIL - %s\n", e.what());
    }
}

void test_invalid() {
    using namespace ninfer::media;
    std::printf("[TEST] decode_image on garbage (should throw)\n");
    try {
        const std::vector<std::uint8_t> junk{1, 2, 3, 4, 5};
        (void)decode::decode_image(junk, {});
        std::printf("  RESULT: FAIL (did not throw)\n");
    } catch (const decode::Error& e) {
        std::printf("  RESULT: PASS - rejected: %s\n", e.what());
    }
}

void test_local_media(const char* path) {
    using namespace ninfer::product::media_acquire;
    std::printf("[TEST] acquire_bytes Path = %s\n", path);
    try {
        Source source;
        source.kind  = SourceKind::Path;
        source.value = path;
        const auto bytes = acquire_bytes(source, {});
        std::printf("  RESULT: PASS - %zu bytes\n", bytes.size());
    } catch (const std::exception& e) {
        std::printf("  RESULT: FAIL - %s\n", e.what());
    }
}

void test_http(const char* url) {
    using namespace ninfer::product::media_acquire;
    std::printf("[TEST] acquire_bytes Url = %s\n", url);
    try {
        Source source;
        source.kind  = SourceKind::Url;
        source.value = url;
        Policy policy;
        policy.max_bytes     = 4096;
        policy.timeout_ms    = 8000;
        policy.connect_timeout_ms = 4000;
        policy.allow_remote  = true;
        const auto bytes = acquire_bytes(source, policy);
        std::printf("  RESULT: PASS - %zu bytes\n", bytes.size());
    } catch (const std::exception& e) {
        std::printf("  RESULT: FAIL - %s\n", e.what());
    }
}

} // namespace

int main(int argc, char** argv) {
    test_image();
    test_invalid();
    test_local_media(argc > 1 ? argv[1] : "media-probe-does-not-exist.bin");
    test_http(argc > 2 ? argv[2] : "http://example.com/");
    return 0;
}
