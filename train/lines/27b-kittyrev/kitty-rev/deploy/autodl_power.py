#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""autodl_power.py — AutoDL 实例开关机（带 SSH 就绪等待、关机前进程检查、超时兜底）

背景
  AutoDL 容器内 poweroff/halt/systemctl/sysrq 全部无效（PID 1 受内核信号保护），
  关机后 SSH 端口消失，也没有带内通道能再开机。
  ⇒ 唯一可控路径是官方 Web API（浏览器登录后的 JWT 直接当 authorization 用）。

凭据
  token : 环境变量 AUTODL_TOKEN  或  deploy/.autodl_token（一行 JWT）
  uuid  : 环境变量 AUTODL_UUID   或  deploy/.autodl_uuid（一行实例 uuid）
  token 来自浏览器 localStorage['token']（登录 www.autodl.com 后 F12 可取），
  JWT 带 exp，过期需重新取。

用法
  python autodl_power.py status
  python autodl_power.py on   [--wait 420]
  python autodl_power.py off  [--force]

判据
  · on  成功 = API 回 code=Success 且 轮询到 status=running 且 TCP ssh_port 可连
  · off 成功 = 同上，status 变 shutdown 且 TCP 不可连
  · --force 跳过「远端还有训练进程」的检查（默认拒绝关机以防杀训练）
"""
import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(HERE, ".autodl_token")
UUID_FILE = os.path.join(HERE, ".autodl_uuid")
BASE = "https://www.autodl.com/api/v1"
APPVER = "v6.52.0"


def _sidecar(name: str, default: str = "") -> str:
    """读侧车文件（环境变量 > deploy/ > deploy/cloud/），避免机房 SSH_HOST 硬编码。
    换机房只改 .autodl_host，脚本不动（2026-11-01 实例迁到 bjb2 后硬编码 bjb1 会误判）。"""
    for d in (HERE, os.path.join(HERE, "cloud")):
        p = os.path.join(d, name)
        if os.path.isfile(p):
            try:
                with open(p, encoding="utf-8") as f:
                    v = f.read().strip()
                if v:
                    return v
            except OSError:
                pass
    return default


SSH_HOST = _sidecar(".autodl_host", "connect.bjb1.seetacloud.com")


def _read(path, envkey):
    v = os.environ.get(envkey, "").strip()
    if v:
        return v
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip()
    return ""


def token():
    t = _read(TOKEN_FILE, "AUTODL_TOKEN")
    if not t:
        die("缺 token：设 AUTODL_TOKEN 或写 deploy/.autodl_token"
            "（浏览器 localStorage['token']）")
    return t


def uuid():
    return _read(UUID_FILE, "AUTODL_UUID")


def die(msg, code=2):
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(code)


def api(path, body=None, timeout=30):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
        "authorization": token(),
        "appversion": APPVER,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/155",
        "referer": "https://www.autodl.com/console/instance/list",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return {"code": f"HTTP{e.code}", "msg": e.read().decode("utf-8", "replace")[:300]}
    except Exception as e:
        return {"code": "EXC", "msg": f"{type(e).__name__}: {e}"}


def inst():
    """取目标实例（默认第一条；可用 AUTODL_UUID 指定）"""
    j = api("/instance", {"page_index": 1, "page_size": 50})
    if j.get("code") != "Success":
        die(f"列表查询失败: {j}")
    arr = ((j.get("data") or {}).get("list") or [])
    if not arr:
        die("账号下没有实例")
    want = uuid()
    if want:
        for it in arr:
            if it.get("uuid") == want:
                return it
        die(f"找不到 uuid={want} 的实例（现有: {[x.get('uuid') for x in arr]}）")
    return arr[0]


def tcp_ok(host, port, timeout=5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def cmd_status(a):
    it = inst()
    host = it.get("ssh_host") or SSH_HOST
    port = it.get("ssh_port")
    st = it.get("status")
    ssh = tcp_ok(host, port) if st == "running" and port else False
    print(json.dumps({
        "uuid": it.get("uuid"), "name": it.get("name"), "status": st,
        "status_text": it.get("status_text"), "region": it.get("region_sign"),
        "machine": it.get("machine_id"), "charge": it.get("charge_type"),
        "gpu": it.get("gpu_spec_uuid"),
        "ssh": f"{host}:{port}", "ssh_reachable": ssh,
        "release": it.get("release_time") or it.get("stop_time"),
    }, ensure_ascii=False, indent=1))
    return 0 if ssh or st == "shutdown" else 1


def cmd_on(a):
    it = inst()
    if it.get("status") == "running":
        print(f"[=] 已是 running，uuid={it.get('uuid')} 跳过开机")
    else:
        j = api("/instance/power_on", {"instance_uuid": it.get("uuid")})
        if j.get("code") != "Success":
            die(f"开机请求失败: {j}")
        print(f"[+] power_on 已受理 uuid={it.get('uuid')}（原状态 {it.get('status')}）")

    host = it.get("ssh_host") or SSH_HOST
    port = it.get("ssh_port")
    t0 = time.time()
    while time.time() - t0 < a.wait:
        it2 = inst()
        st = it2.get("status")
        ok = st == "running" and tcp_ok(host, port)
        el = int(time.time() - t0)
        print(f"    [{el:>4}s] status={st:<10} ssh={host}:{port} reachable={ok}", flush=True)
        if ok:
            print(f"[OK] 实例就绪，用时 {el}s → ssh {host} -p {port}")
            return 0
        time.sleep(10)
    die(f"等 {a.wait}s 仍未就绪（最后 status={it2.get('status') if 'it2' in dir() else '?'}）", 1)


def remote_running_tasks():
    """尽力而为：通过 SSH 看有没有 python 训练进程（无 paramiko 或连不上就返回 None）"""
    try:
        import paramiko
    except ImportError:
        return None
    host = os.environ.get("AUTODL_HOST", SSH_HOST)
    port = int(os.environ.get("AUTODL_PORT", "35299"))
    user = os.environ.get("AUTODL_USER", "root")
    pw = os.environ.get("AUTODL_PASS", "")
    if not pw:
        return None
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(host, port=port, username=user, password=pw, timeout=15,
                  banner_timeout=15, look_for_keys=False, allow_agent=False)
        _in, out, _err = c.exec_command(
            "ps -eo pid,etime,cmd | grep -E '[t]rain_kitty|[c]hain_repair|[l]lama-quantize' | head -5")
        s = out.read().decode("utf-8", "replace").strip()
        c.close()
        return s
    except Exception as e:
        return f"<ssh-probe-failed: {type(e).__name__}>"


def cmd_off(a):
    it = inst()
    if it.get("status") == "shutdown":
        print(f"[=] 已是 shutdown，uuid={it.get('uuid')} 跳过关机")
        return 0
    if not a.force:
        r = remote_running_tasks()
        if r:
            print("[!] 远端仍有进程在跑，拒绝关机（要强关加 --force）：")
            print(r)
            return 3
        if r is None:
            print("[warn] 无法探测远端进程（缺 paramiko/AUTODL_PASS），继续关机")
    j = api("/instance/power_off", {"instance_uuid": it.get("uuid")})
    if j.get("code") != "Success":
        die(f"关机请求失败: {j}")
    print(f"[+] power_off 已受理 uuid={it.get('uuid')}")
    host = it.get("ssh_host") or SSH_HOST
    port = it.get("ssh_port")
    t0 = time.time()
    while time.time() - t0 < a.wait:
        it2 = inst()
        st = it2.get("status")
        down = st == "shutdown" and not tcp_ok(host, port)
        print(f"    [{int(time.time()-t0):>4}s] status={st:<10} ssh_reachable={tcp_ok(host, port)}", flush=True)
        if down:
            print(f"[OK] 已关机，用时 {int(time.time()-t0)}s（计费已停）")
            return 0
        time.sleep(10)
    die(f"等 {a.wait}s 仍未确认关机（最后 status={it2.get('status') if 'it2' in dir() else '?'}）", 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "on", "off"])
    ap.add_argument("--wait", type=int, default=420, help="等待就绪/关机的秒数上限")
    ap.add_argument("--force", action="store_true", help="off 时跳过远端进程检查")
    a = ap.parse_args()
    return {"status": cmd_status, "on": cmd_on, "off": cmd_off}[a.action](a)


if __name__ == "__main__":
    sys.exit(main() or 0)
