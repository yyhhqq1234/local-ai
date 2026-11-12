import json
import os
import re
import subprocess
import sys

BASE = r"D:\BaiduNetdiskDownload\Local-AI\_work\ninfer-9b"
EXE = r"D:\BaiduNetdiskDownload\Local-AI\engines\llama-cpp\llama-bin\llama-perplexity.exe"
CORPUS = os.path.join(BASE, "ppl-corpus.txt")
GG = r"D:\BaiduNetdiskDownload\Local-AI\models\9b\gguf"

MODELS = sys.argv[1:] or ["kittyrev9b-Q5_K_M-im.gguf"]

for m in MODELS:
    path = os.path.join(GG, m)
    if not os.path.isfile(path):
        print(json.dumps({"model": m, "error": "missing"}), flush=True)
        continue
    r = subprocess.run([EXE, "-m", path, "-f", CORPUS, "-c", "512", "--chunks", "16",
                        "-ngl", "99", "--no-warmup"],
                       capture_output=True, text=True, timeout=7200)
    out = (r.stdout or "") + (r.stderr or "")
    ppls = re.findall(r"Final estimate:\s*PPL\s*=\s*([0-9.]+)", out)
    ppl = ppls[-1] if ppls else None
    print(json.dumps({"model": m, "ppl": ppl, "rc": r.returncode}), flush=True)



