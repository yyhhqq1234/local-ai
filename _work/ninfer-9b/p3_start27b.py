import json
import os
import sys

PKG = r"D:\BaiduNetdiskDownload\Local-AI\engines\ninfer-27b\ninfer-27b-kv-stream-3arch-20261019"
sys.path.insert(0, PKG)
os.chdir(PKG)

import launcher  # noqa: E402

try:
    print("PROFILES:", json.dumps(launcher.load_profiles()[0].get("profiles", [])[:3], ensure_ascii=False)[:600])
except Exception as e:
    print("profiles err", e)

try:
    res = launcher.do_start("8g-fast")
    print("START:", json.dumps(res, ensure_ascii=False)[:1200])
except Exception as e:
    import traceback
    traceback.print_exc()

