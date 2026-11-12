import io

P = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\p3_capability_probe_v2.py"
s = io.open(P, encoding="utf-8").read()

s = s.replace(
    'BIN = os.path.join(BASE, "llama-bin", "llama-server.exe")',
    'BIN = r"D:\\BaiduNetdiskDownload\\Local-AI\\engines\\llama-cpp\\llama-bin\\llama-server.exe"')
s = s.replace(
    'GG = os.path.join(BASE, "gguf")',
    'GG = r"D:\\BaiduNetdiskDownload\\Local-AI\\models\\9b\\gguf"')

io.open(P, "w", encoding="utf-8").write(s)
print("ok")
