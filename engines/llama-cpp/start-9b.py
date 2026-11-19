"""9B 一键启动器（DSH 插件与命令行共用）

用法（解释器必须用全路径 C:\\ProgramData\\anaconda3\\python.exe）：
  python start-9b.py                          # 默认 256k 档
  python start-9b.py status                   # 状态 + 实际 n_ctx + 参数
  python start-9b.py stop                     # 停止
  python start-9b.py 256k                     # 切档（fast|32k|128k|256k）
  python start-9b.py 256k --ngl 99 --batch 2048 --ubatch 1024 \
      --cache-type-k q8_0 --cache-type-v q8_0 --no-kv-offload --port 8080
  （所有 llama-server 参数均可调，落 run/active-tier.json 供插件读取）

设计要点：
  · 唯一真相源 = /v1/models 的 meta.n_ctx（DSH 选择器读的就是它），不是 bat 字面量。
  · 档位只提供默认参数；任何参数可被命令行覆盖 → 动态拼 llama-server 命令行，不再依赖固定 bat。
  · 每次输出单行 JSON，便于插件解析。
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

BASE = r"D:\BaiduNetdiskDownload\Local-AI"
ENG = os.path.join(BASE, "engines", "llama-cpp")
RUN = os.path.join(ENG, "run")
STATE = os.path.join(RUN, "active-tier.json")
PORT = 8080
MODEL = os.path.join(BASE, "models", "9b", "gguf", "kittyrev9b-Q5_K_M-im.gguf")
EXE = os.path.join(ENG, "llama-bin", "llama-server.exe")

# 档位默认参数（ctx + 配套 KV / batch）
TIER_DEFAULTS = {
    "fast": {"ctx": 8192, "cacheTypeK": "f16", "cacheTypeV": "f16", "batch": 2048, "ubatch": 1024, "noKvOffload": False, "speed": "70-75 tok/s"},
    "32k": {"ctx": 32768, "cacheTypeK": "q8_0", "cacheTypeV": "q8_0", "batch": 1024, "ubatch": 512, "noKvOffload": False, "speed": "65-72 tok/s"},
    "128k": {"ctx": 131072, "cacheTypeK": "q8_0", "cacheTypeV": "q8_0", "batch": 1024, "ubatch": 512, "noKvOffload": False, "speed": "~44 tok/s"},
    "256k": {"ctx": 262144, "cacheTypeK": "q8_0", "cacheTypeV": "q8_0", "batch": 2048, "ubatch": 1024, "noKvOffload": True, "speed": "~20-35 tok/s"},
}

GLOBAL_DEFAULTS = {"ngl": 99, "port": PORT, "flashAttn": True, "extraArgs": []}
ALL_DEFAULTS = {**GLOBAL_DEFAULTS, "tier": "256k", **TIER_DEFAULTS["256k"]}


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def nvidia_smi():
    hits = glob.glob(r"C:\Windows\System32\DriverStore\FileRepository\nvtfi.inf_amd64_*\nvidia-smi.exe")
    return hits[0] if hits else "nvidia-smi"


def vram_free_mb():
    try:
        out = subprocess.run([nvidia_smi(), "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=8).stdout.strip()
        return int(out.splitlines()[0])
    except Exception:
        return None


def get_json(path, timeout=2):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=timeout) as r:
        return json.loads(r.read())


def health():
    try:
        return get_json("/health", 2).get("status") == "ok"
    except Exception:
        return False


def live_ctx():
    try:
        data = get_json("/v1/models", 3)
        first = (data.get("data") or [])[0]
        meta = first.get("meta") or {}
        return int(first.get("context_window") or meta.get("n_ctx") or 0) or None
    except Exception:
        return None


def model_id():
    try:
        return (get_json("/v1/models", 3).get("data") or [{}])[0].get("id")
    except Exception:
        return None


def is_mine():
    """只认自己的 GGUF：避免把同端口的 27B（j27b）误判为 9B 已启动。"""
    mid = model_id()
    return bool(mid) and "kittyrev9b" in str(mid).lower()


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


def pick_auto():
    free = vram_free_mb()
    if free is None or free >= 7200:
        return "256k"
    if free >= 5200:
        return "fast"
    return "fast"


def stop():
    subprocess.run(["taskkill", "/F", "/IM", "llama-server.exe"], capture_output=True)
    for _ in range(30):
        if not health():
            break
        time.sleep(0.5)
    try:
        os.remove(STATE)
    except OSError:
        pass


def build_cmd(p):
    """按参数拼 llama-server 命令行（全部参数来自配置/命令行）。"""
    a = [EXE, "-m", MODEL, "-ngl", str(p["ngl"]), "-c", str(p["ctx"]),
         "-b", str(p["batch"]), "-ub", str(p["ubatch"]),
         "--cache-type-k", p["cacheTypeK"], "--cache-type-v", p["cacheTypeV"],
         "--host", "127.0.0.1", "--port", str(p["port"]),
         "--jinja", "--no-warmup", "--reasoning-format", "none",
         "--parallel", "1", "--metrics"]
    if p.get("flashAttn", True):
        a += ["-fa", "on"]
    if p.get("noKvOffload"):
        a += ["--no-kv-offload"]
    for x in (p.get("extraArgs") or []):
        a.append(str(x))
    return a


def start(tier, overrides):
    tier = str(tier or "auto").lower()
    if tier not in TIER_DEFAULTS and tier != "auto":
        emit({"ok": False, "err": "unknown tier: %s (fast|32k|128k|256k|auto)" % tier})
        return
    chosen = pick_auto() if tier == "auto" else tier
    p = {**ALL_DEFAULTS, **TIER_DEFAULTS[chosen], "tier": chosen,
         "ctx": TIER_DEFAULTS[chosen]["ctx"], **overrides}

    if is_mine() and live_ctx() == int(p["ctx"]) and read_state().get("tier") == chosen:
        emit({"ok": True, "already": True, "tier": chosen, "contextWindow": live_ctx(),
              "model": model_id(), "params": p})
        return
    stop()
    if not os.path.exists(EXE):
        emit({"ok": False, "err": "missing " + EXE})
        return
    log = os.path.join(ENG, "llama-%s.log" % chosen)
    cmd = build_cmd(p)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("\n[start-9b] " + " ".join(cmd) + "\n")
        subprocess.Popen(cmd, cwd=ENG, stdout=fh, stderr=subprocess.STDOUT,
                         creationflags=0x00000010 | 0x00000200, close_fds=True)
    deadline = time.time() + 300
    while time.time() < deadline:
        time.sleep(1.5)
        ctx = live_ctx()
        if is_mine() and ctx == int(p["ctx"]):
            write_state(p)
            emit({"ok": True, "already": False, "tier": chosen, "contextWindow": ctx,
                  "speed": p.get("speed"), "model": model_id(),
                  "vramFreeMb": vram_free_mb(), "params": p})
            return
    emit({"ok": False, "tier": chosen, "err": "llama-server 未在 300s 内就绪/换档，见 " + log})


def status():
    ctx = live_ctx()
    st = read_state()
    tier = st.get("tier")
    if ctx:
        matched = [k for k, v in TIER_DEFAULTS.items() if v["ctx"] == ctx]
        tier = matched[0] if matched else tier
    emit({"running": is_mine(), "tier": tier, "contextWindow": ctx if is_mine() else None,
          "model": model_id(), "vramFreeMb": vram_free_mb(), "params": st,
          "tiers": {k: {"ctx": v["ctx"], "speed": v["speed"]} for k, v in TIER_DEFAULTS.items()}})


def build_parser():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("cmd", nargs="?", default="auto", help="档位名 | stop | status | auto")
    ap.add_argument("--ngl", type=int, default=None)
    ap.add_argument("--batch", type=int, default=None)
    ap.add_argument("--ubatch", type=int, default=None)
    ap.add_argument("--cache-type-k", default=None)
    ap.add_argument("--cache-type-v", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--no-kv-offload", dest="no_kv_offload", action="store_true", default=None)
    ap.add_argument("--kv-offload", dest="no_kv_offload", action="store_false")
    ap.add_argument("--no-fa", dest="flashAttn", action="store_false", default=None)
    ap.add_argument("--extra-arg", action="append", default=None)
    return ap


def merged_overrides(args):
    ov = {}
    if args.ngl is not None: ov["ngl"] = args.ngl
    if args.batch is not None: ov["batch"] = args.batch
    if args.ubatch is not None: ov["ubatch"] = args.ubatch
    if args.cache_type_k: ov["cacheTypeK"] = args.cache_type_k
    if args.cache_type_v: ov["cacheTypeV"] = args.cache_type_v
    if args.port is not None: ov["port"] = args.port
    if args.no_kv_offload is not None: ov["noKvOffload"] = args.no_kv_offload
    if args.flashAttn is not None: ov["flashAttn"] = args.flashAttn
    if args.extra_arg: ov["extraArgs"] = args.extra_arg
    return ov


if __name__ == "__main__":
    ap = build_parser()
    args = ap.parse_args()
    cmd = args.cmd.lower()
    if cmd == "stop":
        stop()
        emit({"ok": True, "stopped": True})
    elif cmd == "status":
        status()
    else:
        start(cmd, merged_overrides(args))
