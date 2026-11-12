import json
import os
import subprocess
import sys
import time
import urllib.request

PKG = r"D:\BaiduNetdiskDownload\Local-AI\engines\ninfer-27b\ninfer-27b-kv-stream-3arch-20261019"
sys.path.insert(0, PKG)
os.chdir(PKG)
import launcher  # noqa: E402

spec = launcher.load_profiles()
print("spec keys:", list(spec)[:8])
pre = launcher.preflight("8g-fast")
profile = pre["profile"]
arch = pre["arch"]["arch"]
argv = list(pre["command"]["argv"])


def set_arg(a, flag, value):
    if flag in a:
        a[a.index(flag) + 1] = str(value)
    else:
        a += [flag, str(value)]


set_arg(argv, "--prefill-chunk", 128)
set_arg(argv, "--max-context", 8192)
set_arg(argv, "--kv-capacity", 4096)
set_arg(argv, "--host-kv-mib", 1024)
set_arg(argv, "--max-concurrency", 1)

log_path = os.path.join(PKG, "logs", "custom-27b.log")
open(log_path, "wb").close()
with open(log_path, "ab", buffering=0) as fh:
    p = subprocess.Popen(argv, cwd=str(launcher.ENGINES / arch),
                         env=launcher.build_env(spec, profile),
                         stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                         creationflags=0x00000010 | 0x00000200)
print("pid", p.pid)
print("argv", " ".join(argv)[:500])
for i in range(40):
    time.sleep(2)
    if p.poll() is not None:
        print("exited", p.returncode)
        break
    try:
        urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % int(spec.get("engine_port", 8080)), timeout=2).read()
        print("READY after", (i + 1) * 2, "s")
        break
    except Exception:
        pass
print("---- log tail ----")
with open(log_path, encoding="utf-8", errors="ignore") as fh:
    print("\n".join(fh.read().splitlines()[-10:]))

