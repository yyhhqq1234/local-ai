import re, io
p = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-master\src\ops\sampling\sample\entry.cpp"
s = io.open(p, encoding="utf-8-sig").read()
# 1) 删 logits dump 块（从注释到紧随其后的空行）
s = re.sub(r"\n    // \[9B 诊断\] dump logits.*?\n    }\n\n", "\n", s, flags=re.S)
# 2) 删 clamp 实验块
s = re.sub(r"\n    // \[9B 实验\] 高位 token 保护.*?\n    }\n", "\n", s, flags=re.S)
# 3) 若还有残留的 dump 注释行，一并清
s = re.sub(r"\n *// \[9B [^\n]*\n(?=(?: *\n)*? *auto scratch_scope)", "\n", s)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("剩余诊断痕迹：", s.count("cudaDeviceSynchronize"), "个 sync,", s.count("std::vector<unsigned short> all"), "个全vocab扫描")
