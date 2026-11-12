"""模型/引擎切换：9B（llama.cpp 8080）与 27B（NInfer 8081）互斥（显存不够同时跑）。

用法：
  python switch-model.py status
  python switch-model.py 9b [fast|128k|256k]
  python switch-model.py 27b
  python switch-model.py stop
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
PY = r"C:\ProgramData\anaconda3\python.exe"
PY27 = os.path.join(BASE, "engines", "ninfer-27b", "ninfer-27b-kv-stream-3arch-20261019",
                    "runtime", "python", "python.exe")
SW9 = os.path.join(BASE, "engines", "llama-cpp", "switch-9b.py")
START27 = os.path.join(BASE, "engines", "ninfer-27b", "start-27b.py")
SMI = r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_540239129807163b\nvidia-smi.exe"


def stop_all():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    time.sleep(3)


def probe(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % port, timeout=3) as r:
            return [m.get("id") for m in json.loads(r.read()).get("data", [])]
    except Exception:
        return None


def status():
    out = {"8080": probe(8080), "8081": probe(8081)}
    try:
        out["vram_free_mb"] = int(subprocess.run(
            [SMI, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True).stdout.strip())
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False))


def wait(port, secs=480):
    for i in range(secs // 2):
        time.sleep(2)
        if probe(port) is not None:
            return True
    return False


def main():
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd == "status":
        return status()
    if cmd == "stop":
        stop_all()
        print('{"ok": true, "stopped": true}')
        return
    if cmd == "9b":
        tier = sys.argv[2] if len(sys.argv) > 2 else "fast"
        stop_all()
        subprocess.run([PY, SW9, tier], capture_output=True)
        print(json.dumps({"ok": wait(8080), "engine": "9b", "tier": tier, "port": 8080}, ensure_ascii=False))
        return
    if cmd == "27b":
        stop_all()
        subprocess.Popen([PY27, START27], cwd=os.path.dirname(START27),
                         creationflags=0x00000010 | 0x00000200,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(json.dumps({"ok": wait(8081), "engine": "27b", "port": 8081}, ensure_ascii=False))
        return
    print('{"ok": false, "err": "usage: status|9b [fast|128k|256k]|27b|stop"}')


main()
