"""一键切档：start / status / stop。三档见 engines/llama-cpp/serve*.bat

用法：
  python switch-9b.py status
  python switch-9b.py fast      # 32k 设备 KV，decode 70–75
  python switch-9b.py 128k      # 128k 设备 KV，decode ~44
  python switch-9b.py 256k      # 256k 主机 KV，decode ~20（长文 prefill 正常）
  python switch-9b.py stop
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
ENG = os.path.join(BASE, "engines", "llama-cpp")
BATS = {
    "fast": os.path.join(ENG, "serve.bat"),
    "128k": os.path.join(ENG, "serve-9b-128k.bat"),
    "256k": os.path.join(ENG, "serve-9b-256k.bat"),
}
PORT = 8080


def stop():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    time.sleep(3)


def status():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % PORT, timeout=3) as r:
            body = json.loads(r.read())
        out = {"up": True, "models": [m.get("id") for m in body.get("data", [])]}
    except Exception as e:
        out = {"up": False, "err": str(e)[:60]}
    try:
        out["vram_free_mb"] = int(subprocess.run(
            [r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_540239129807163b\nvidia-smi.exe",
             "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True).stdout.strip())
    except Exception:
        pass
    print(json.dumps(out, ensure_ascii=False))


def start(tier):
    bat = BATS[tier]
    if not os.path.exists(bat):
        print(json.dumps({"ok": False, "err": "missing " + bat}, ensure_ascii=False))
        return
    stop()
    subprocess.Popen(["cmd", "/c", bat], cwd=ENG,
                     creationflags=0x00000010 | 0x00000200,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(240):
        time.sleep(2)
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=2).read()
            print(json.dumps({"ok": True, "tier": tier, "waited_s": (i + 1) * 2}, ensure_ascii=False))
            return
        except Exception:
            pass
    print(json.dumps({"ok": False, "tier": tier, "err": "not ready in 480s"}, ensure_ascii=False))


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if cmd == "stop":
        stop(); print('{"ok": true, "stopped": true}')
    elif cmd == "status":
        status()
    elif cmd in BATS:
        start(cmd)
    else:
        print('{"ok": false, "err": "usage: fast|128k|256k|status|stop"}')
