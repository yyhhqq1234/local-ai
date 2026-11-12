// 临时探针：NINFER_DUMP_PROMPT=<path> 时把渲染后的完整 prompt 落盘
import fs from 'node:fs'
const P = 'D:/BaiduNetdiskDownload/Local-AI/train/lines/_shared/tools/ninfer-master/src/models/common/qwen/frontend/chat_template.cpp'
let s = fs.readFileSync(P, 'utf8')
const from = '    auto output = compiled_.render(context, execution);'
const to = `    auto output = compiled_.render(context, execution);
    if (const char* dump = std::getenv("NINFER_DUMP_PROMPT"); dump != nullptr && *dump) {
        std::FILE* f = std::fopen(dump, "ab");
        if (f != nullptr) {
            std::fwrite(output.text.data(), 1, output.text.size(), f);
            std::fwrite("\\n=====REQ=====\\n", 1, 14, f);
            std::fclose(f);
        }
    }`
const n = s.split(from).length - 1
if (n !== 1) throw new Error('anchor=' + n)
s = s.replace(from, () => to)
if (!s.includes('#include <cstdio>')) {
  s = s.replace('#include "models/common/qwen/frontend/chat_template.h"',
    '#include "models/common/qwen/frontend/chat_template.h"\n\n#include <cstdio>\n#include <cstdlib>')
}
fs.writeFileSync(P, s, 'utf8')
console.log('probe added')
