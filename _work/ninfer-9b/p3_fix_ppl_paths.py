import io

P = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b\p3_ppl_compare.py"
s = io.open(P, encoding="utf-8").read()

s = s.replace('EXE = os.path.join(BASE, "llama-bin", "llama-perplexity.exe")',
              'EXE = r"D:\\BaiduNetdiskDownload\\Local-AI\\engines\\llama-cpp\\llama-bin\\llama-perplexity.exe"')
s = s.replace('GG = os.path.join(BASE, "gguf")',
              'GG = r"D:\\BaiduNetdiskDownload\\Local-AI\\models\\9b\\gguf"')
s = s.replace('MODELS = sys.argv[1:] or ["kittyrev9b-Q6_K.gguf", "kittyrev9b-Q5_K_M-im.gguf"]',
              'MODELS = sys.argv[1:] or ["kittyrev9b-Q5_K_M-im.gguf"]')

io.open(P, "w", encoding="utf-8").write(s)
print("ppl paths fixed")
