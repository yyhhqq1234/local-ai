"""27B 上下文扩容实验：找到能开 256k+ 且留 500 MB 显存的组合。

用法：
  runtime\\python\\python.exe p3_27b_ctx.py <kv_capacity> <ctx> <host_kv_mib> <chunk> [reserve_mib]
输出：JSON（ok / free_vram_mb / log 尾部错误）
"""
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

SMI = r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_540239129807163b\nvidia-smi.exe"


def set_arg(a, flag, value):
    if flag in a:
        a[a.index(flag) + 1] = str(value)
    else:
        a += [flag, str(value)]


def free_mb():
    out = subprocess.run([SMI, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(out.splitlines()[0])
    except Exception:
        return -1


def main():
    kv = int(sys.argv[1]); ctx = int(sys.argv[2]); hostkv = int(sys.argv[3]); chunk = int(sys.argv[4])
    reserve = int(sys.argv[5]) if len(sys.argv) > 5 else 512
    dtype = sys.argv[6] if len(sys.argv) > 6 else "rk2v4-e8"
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    time.sleep(3)
    pre = launcher.preflight("8g-fast")
    profile = dict(pre["profile"])
    profile["reserve_mib"] = reserve
    arch = pre["arch"]["arch"]
    argv = list(pre["command"]["argv"])
    set_arg(argv, "--prefill-chunk", chunk)
    set_arg(argv, "--kv-capacity", kv)
    set_arg(argv, "--max-context", ctx)
    set_arg(argv, "--host-kv-mib", hostkv)
    set_arg(argv, "--kv-dtype", dtype)
    set_arg(argv, "--max-concurrency", 1)
    log_path = os.path.join(PKG, "logs", "ctx-%d.log" % kv)
    open(log_path, "wb").close()
    with open(log_path, "ab", buffering=0) as fh:
        p = subprocess.Popen(argv, cwd=str(launcher.ENGINES / arch),
                             env=launcher.build_env(launcher.load_profiles(), profile),
                             stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=0x00000010 | 0x00000200)
    port = int(launcher.load_profiles().get("engine_port", 8080))
    ready = False
    for _ in range(45):
        time.sleep(2)
        if p.poll() is not None:
            break
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % port, timeout=2).read()
            ready = True
            break
        except Exception:
            pass
    err = ""
    if not ready:
        with open(log_path, encoding="utf-8", errors="ignore") as fh:
            bad = [l for l in fh.read().splitlines() if "FATAL" in l or "ERROR" in l]
            err = bad[-1][:200] if bad else "(no error line)"
    print(json.dumps({"kv": kv, "ctx": ctx, "host_kv_mib": hostkv, "chunk": chunk,
                      "reserve_mib": reserve, "dtype": dtype, "ok": ready, "free_vram_mb": free_mb(),
                      "error": err}, ensure_ascii=False))


main()

