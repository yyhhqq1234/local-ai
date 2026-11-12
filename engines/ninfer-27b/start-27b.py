"""启动 27B（NInfer, Huihui-Swift IQ2_S）—— 12 GB 卡实测最优参数。

用法（在任意目录）：
    D:\\...\\engines\\ninfer-27b\\ninfer-27b-kv-stream-3arch-20261019\\runtime\\python\\python.exe start-27b.py

实测（2026-11-12，RTX 5070 Ti Laptop 12 GB）：
    --prefill-chunk 512 --kv-capacity 4096 --max-context 8192
    decode 76.0 tok/s · prefill 1078 tok/s · TTFT(2.8k) 2.6 s · MTP 接受 57/70 = 81%
    chunk 1024 会 FATAL（runtime 要 2.19 GB，只剩 1.99 GB）
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

PKG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ninfer-27b-kv-stream-3arch-20261019")
sys.path.insert(0, PKG)
os.chdir(PKG)
import launcher  # noqa: E402

CHUNK = 128
KV = 32768
CTX = 262144
HOST_KV = 8192
PORT_27B = 8080


def set_arg(a, flag, value):
    if flag in a:
        a[a.index(flag) + 1] = str(value)
    else:
        a += [flag, str(value)]


def main():
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    time.sleep(3)
    pre = launcher.preflight("8g-fast")
    profile = pre["profile"]
    arch = pre["arch"]["arch"]
    argv = list(pre["command"]["argv"])
    set_arg(argv, "--prefill-chunk", CHUNK)
    set_arg(argv, "--kv-capacity", KV)
    set_arg(argv, "--max-context", CTX)
    set_arg(argv, "--host-kv-mib", HOST_KV)
    set_arg(argv, "--max-concurrency", 1)
    os.makedirs(os.path.join(PKG, "logs"), exist_ok=True)
    log = os.path.join(PKG, "logs", "serve-27b.log")
    open(log, "wb").close()
    with open(log, "ab", buffering=0) as fh:
        p = subprocess.Popen(argv, cwd=str(launcher.ENGINES / arch),
                             env=launcher.build_env(launcher.load_profiles(), profile),
                             stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=0x00000010 | 0x00000200)
    port = int(launcher.load_profiles().get("engine_port", 8080))
    for _ in range(45):
        time.sleep(2)
        if p.poll() is not None:
            break
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % port, timeout=2).read()
            print(json.dumps({"ok": True, "pid": p.pid, "port": port,
                              "chunk": CHUNK, "kv": KV, "ctx": CTX,
                              "log": log}, ensure_ascii=False))
            return
        except Exception:
            pass
    print(json.dumps({"ok": False, "log": log}, ensure_ascii=False))


if __name__ == "__main__":
    main()





