import io
p = r"D:\BaiduNetdiskDownload\Local-AI\train\lines\_shared\tools\ninfer-master\src\ops\sampling\sample\entry.cpp"
L = io.open(p, encoding="utf-8-sig").read().splitlines()
# 删除 1-based 行 61..136（诊断块），保留其余
kept = L[:60] + L[136:]
io.open(p, "w", encoding="utf-8", newline="\n").write("\n".join(kept) + "\n")
print("原 %d 行 -> 现 %d 行（删了 %d 行）" % (len(L), len(kept), len(L)-len(kept)))
