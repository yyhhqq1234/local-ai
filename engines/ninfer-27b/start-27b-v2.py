"""27B NInfer 一键启动器（DSH 插件与命令行共用）

用法（解释器必须用 27B 自带 runtime python）：
  python start-27b.py                    # 默认参数启动（一键）
  python start-27b.py status             # 状态 + 实际 n_ctx + 参数
  python start-27b.py stop               # 停止
  python start-27b.py --prefill-chunk 128 --kv-capacity 32768 --max-context 262144 \
                      --host-kv-mib 8192 --port 8080 --draft-tokens 3 --reasoning-effort medium

所有引擎参数均可调；每次输出单行 JSON，供 DSH 插件解析。
参数落 engines/ninfer-27b/run/active.json（插件据此判断是否需要换参数重启）。

2026-11-19：原 start-27b.py 是硬编码常量版（CHUNK/KV/CTX/HOST_KV），无法从插件传参。
本文件取代它作为唯一入口；switch-model.py 27b 分支已改为调用本文件。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
ENG27 = os.path.join(BASE, "engines", "ninfer-27b")
PKG = os.path.join(ENG27, "ninfer-27b-kv-stream-3arch-20261019")
# 引擎与模型全部在 PKG 内；解释器由调用方（插件 launcher / switch-model.py）
# 指向 PKG/runtime/python/python.exe，本脚本不依赖任何外部 Python 安装。
RUN = os.path.join(ENG27, "run")
STATE = os.path.join(RUN, "active.json")
PORT_DEFAULT = 8080

# 默认配方（2026-11-12 实测 12G 卡最优）
DEFAULTS = {
    "profileId": "8g-fast",
    "prefillChunk": 128,
    "kvCapacity": 32768,
    "maxContext": 262144,
    "hostKvMib": 8192,
    "port": PORT_DEFAULT,
    "draftTokens": 3,
    "reasoningEffort": "medium",
    "vision": "off",
}

sys.path.insert(0, PKG)
os.chdir(PKG)
import launcher  # noqa: E402


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def set_arg(a, flag, value):
    if flag in a:
        a[a.index(flag) + 1] = str(value)
    else:
        a += [flag, str(value)]


def get_arg(a, flag, default=None):
    try:
        return a[a.index(flag) + 1]
    except (ValueError, IndexError):
        return default


def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(p):
    os.makedirs(RUN, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


MODEL_ID = "j27b"


def probe(port):
    """只认 27B：model id 必须是 j27b，避免把同端口的 9B 误判成自己在跑。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/v1/models" % port, timeout=2) as r:
            d = json.loads(r.read())
        first = (d.get("data") or [{}])[0]
        return d if str(first.get("id", "")).lower() == MODEL_ID else None
    except Exception:
        return None


def live_ctx(port):
    d = probe(port)
    if not d:
        return None
    first = (d.get("data") or [])[0] or {}
    meta = first.get("meta") or {}
    return int(first.get("context_window") or meta.get("n_ctx") or 0) or None


def status():
    st = read_state()
    port = int(st.get("port") or PORT_DEFAULT)
    d = probe(port)
    emit({
        "running": bool(d),
        "model": (d.get("data") or [{}])[0].get("id") if d else None,
        "contextWindow": live_ctx(port),
        "port": port,
        "params": {**DEFAULTS, **st},
        "vramFreeMb": vram_free_mb(),
    })


def vram_free_mb():
    try:
        import glob
        hits = glob.glob(r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_*\nvidia-smi.exe")
        smi = hits[0] if hits else "nvidia-smi"
        out = subprocess.run([smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:
        return None


def stop():
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    for _ in range(30):
        if not probe(int(read_state().get("port") or PORT_DEFAULT)):
            break
        time.sleep(0.5)
    emit({"ok": True, "stopped": True})


def start(params):
    port = int(params["port"])
    st = read_state()
    if probe(port) and live_ctx(port) == int(params["maxContext"]):
        emit({"ok": True, "already": True, "params": params, "contextWindow": live_ctx(port)})
        return
    # 与 9B 互斥：先停 llama-server（9B）再起 27B
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "infer-serve.exe"], capture_output=True)
    time.sleep(3)

    pre = launcher.preflight(params["profileId"])
    argv = list(pre["command"]["argv"])
    set_arg(argv, "--prefill-chunk", params["prefillChunk"])
    set_arg(argv, "--kv-capacity", params["kvCapacity"])
    set_arg(argv, "--max-context", params["maxContext"])
    set_arg(argv, "--host-kv-mib", params["hostKvMib"])
    set_arg(argv, "--port", port)
    set_arg(argv, "--max-concurrency", 1)
    # 思考强度：common_argv 里有 --default-reasoning-effort 模板
    set_arg(argv, "--default-reasoning-effort", params["reasoningEffort"])
    if params.get("draftTokens"):
        set_arg(argv, "--draft-tokens", params["draftTokens"])
    # 视觉：off 时保持默认（模型本身无视觉）；cpu 时若引擎支持再加 flag（当前 27B 无视觉通道）

    os.makedirs(os.path.join(PKG, "logs"), exist_ok=True)
    log = os.path.join(PKG, "logs", "serve-27b.log")
    open(log, "wb").close()
    with open(log, "ab", buffering=0) as fh:
        p = subprocess.Popen(argv, cwd=str(launcher.ENGINES / pre["arch"]["arch"]),
                             env=launcher.build_env(launcher.load_profiles(), pre["profile"]),
                             stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=0x00000010 | 0x00000200)
    for _ in range(240):  # 480s：27B 首次加载 + CUDA Graph
        time.sleep(2)
        if p.poll() is not None:
            emit({"ok": False, "err": "infer-serve exited code=%s" % p.returncode, "log": log})
            return
        ctx = live_ctx(port)
        if ctx:
            write_state(params)
            emit({"ok": True, "already": False, "pid": p.pid, "port": port,
                  "contextWindow": ctx, "params": params, "log": log,
                  "vramFreeMb": vram_free_mb()})
            return
    emit({"ok": False, "err": "not ready in 480s", "log": log})


def build_parser():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?", default="start",
                    help="start | stop | status | （省略则 start）")
    ap.add_argument("--profile-id", default=None)
    ap.add_argument("--prefill-chunk", type=int, default=None)
    ap.add_argument("--kv-capacity", type=int, default=None)
    ap.add_argument("--max-context", type=int, default=None)
    ap.add_argument("--host-kv-mib", type=int, default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--draft-tokens", type=int, default=None)
    ap.add_argument("--reasoning-effort", default=None)
    ap.add_argument("--vision", default=None)
    return ap


def merged_params(args, base):
    p = dict(base)
    if args.profile_id: p["profileId"] = args.profile_id
    if args.prefill_chunk is not None: p["prefillChunk"] = args.prefill_chunk
    if args.kv_capacity is not None: p["kvCapacity"] = args.kv_capacity
    if args.max_context is not None: p["maxContext"] = args.max_context
    if args.host_kv_mib is not None: p["hostKvMib"] = args.host_kv_mib
    if args.port is not None: p["port"] = args.port
    if args.draft_tokens is not None: p["draftTokens"] = args.draft_tokens
    if args.reasoning_effort: p["reasoningEffort"] = args.reasoning_effort
    if args.vision: p["vision"] = args.vision
    return p


if __name__ == "__main__":
    ap = build_parser()
    args = ap.parse_args()
    cmd = args.cmd.lower()
    if cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    elif cmd == "start":
        start(merged_params(args, {**DEFAULTS, **read_state()}))
    else:
        emit({"ok": False, "err": "usage: start|stop|status [--参数 值 ...]"})
