import os
d = os.path.join("D:" + os.sep, "BaiduNetdiskDownload", "Local-AI", "_work", "ninfer-9b")
for f in os.listdir(d):
    if "prefill" in f and f.endswith(".bin"):
        p = os.path.join(d, f)
        try:
            with open(p, "rb") as fh:
                n = len(fh.read())
            print("open ok:", repr(f), n)
        except Exception as exc:
            print("open failed:", repr(f), type(exc).__name__, exc)
