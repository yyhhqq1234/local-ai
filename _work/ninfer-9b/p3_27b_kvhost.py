"""27B：把 KV 放到主机内存/磁盘，尝试真 256k 上下文。

参数：<kv_capacity> <max_context> <host_kv_mib> <chunk> <reserve_mib> [disk_kv_gib]
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
DISK_KV = r"D:\BaiduNetdiskDownload\Local-AI\engines\ninfer-27b\kvdisk"


def set_arg(a, flag, value):
    if flag in a:
        a[a.index(flag) + 1] = str(value)
    else:
        a += [flag, str(value)]


def free_mb():
    out = subprocess.run([SMI, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.strip()
    return int(out.splitlines()[0]) if out else -1


def main():
    kv, ctx, hostkv, chunk, reserve = (int(sys.argv[i]) for i in range(1, 6))
    disk_gib = int(sys.argv[6]) if len(sys.argv) > 6 else 0
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
    set_arg(argv, "--max-concurrency", 1)
    extra = sys.argv[7:]
    if extra:
        argv += extra
    if disk_gib:
        os.makedirs(DISK_KV, exist_ok=True)
        argv += ["--disk-kv-gib", str(disk_gib), "--disk-kv-path", DISK_KV]
    log_path = os.path.join(PKG, "logs", "kvhost-%d-%d.log" % (kv, disk_gib))
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
                      "disk_kv_gib": disk_gib, "ok": ready, "free_vram_mb": free_mb(),
                      "error": err}, ensure_ascii=False))


main()

