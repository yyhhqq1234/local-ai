#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t39_probe_text_uses_jsonl.py -- F24：`--from-jsonl` 必须在 text 模式真的生效。

缺陷现象（改前 md5 6a778e16）
    `measure_text()` 的循环**已经**用 `P = a.prompts or COMPLY`，但
      · 进度行 `[text] {i}/{len(COMPLY)}`
      · 汇总行 `({len(refused)}/{len(COMPLY)})`
      · 报告头 `"comply_n": len(COMPLY)`
    还在按内联 60 打。跑 100 条 → 日志显示 /60 → 看日志的人会把 refusal_rate 算高 1.67 倍。
    这是 F16/F17 同族：**参数生效了，口径没跟上**（比"参数没生效"更难发现）。
   另有一处更硬的分母问题：请求失败被 `continue` 掉，等于计成"非拒答" → 率被拉低。

正确的断言（本测试用本地假服务端，不需要 GPU/模型）
    ① `--from-jsonl 30` → 报告 n=30、n_ok=30、comply_n=30；日志里分母是 /30 不是 /60
    ② 报告里的 list_sha16 == **服务端实际收到的 prompt 集合**算出的 sha16（名单与请求一致）
    ③ 不给 --from-jsonl → n=60（向后兼容，今晚 C/B 用的就是这个口径）
    ④ --from-jsonl 路径打错 → rc=2（不许静默退回 60）
如果这条 FAIL 说明什么
    分母/日志又回到内联 60，或 jsonl 名单与实际请求不是同一批 —— refusal_rate 不可信。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:                       # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
SCRIPT = os.path.join(KITTY, "scripts", "refusal_probe.py")
COMPLY = os.path.join(KITTY, "data", "reablit", "comply_set.jsonl")
PY = sys.executable
fails = []
SEEN = []                                # 服务端实际收到的 prompt（按到达顺序）


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        for m in body.get("messages") or []:
            if m.get("role") == "user":
                SEEN.append(m.get("content") or "")
        payload = {"choices": [{"index": 0, "message": {
            "role": "assistant", "content": "先做这个：用 kitty_die 看节表，再按步骤执行。"}}]}
        out = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"

tmp = tempfile.mkdtemp(prefix="rg-t39-")
try:
    def run(*args, timeout=300):
        p = subprocess.run([PY, SCRIPT, "--base", base, "--model", "fake", *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    # ① --from-jsonl 30
    SEEN.clear()
    out30 = os.path.join(tmp, "r30.json")
    rc, out = run("--from-jsonl", COMPLY, "--limit", "30", "--out", out30)
    check("① 30 条 → rc=0", rc == 0, f"rc={rc}")
    rep = json.load(open(out30, encoding="utf-8")) if os.path.isfile(out30) else {}
    t = rep.get("text") or {}
    check("① 报告 n=30", t.get("n") == 30, str(t.get("n")))
    check("① 报告 n_ok=30（请求全部成功）", t.get("n_ok") == 30, str(t.get("n_ok")))
    check("① 报告 comply_n=30（F24 的核心）", rep.get("comply_n") == 30, str(rep.get("comply_n")))
    check("① 日志分母是 /30 不是 /60", "/30" in out and "/60" not in out.split("[text] refusal_rate")[0].replace("/600", ""),
          [l for l in out.splitlines() if "refusal_rate" in l][:1])
    check("① 日志有 [source] jsonl 30", "[source] jsonl 30" in out,
          [l for l in out.splitlines() if "[source]" in l][:2])
    check("① 服务端确实收到 30 条（不是 60）", len(SEEN) == 30, f"收到了 {len(SEEN)}")

    # ② 名单 sha16 == 实际请求集合的 sha16
    want = hashlib.sha256("\n".join(SEEN).encode("utf-8")).hexdigest()[:16]
    got = t.get("list_sha16") or rep.get("comply_list_sha16")
    check("② 报告 list_sha16 与服务端实收集合一致", got == want, f"report={got} 实测={want}")
    check("② 报告里记了来源", (rep.get("comply_source") or "").endswith("comply_set.jsonl"),
          str(rep.get("comply_source")))

    # ③ 不给 --from-jsonl → 60（向后兼容）
    SEEN.clear()
    out60 = os.path.join(tmp, "r60.json")
    rc, out = run("--out", out60)
    rep6 = json.load(open(out60, encoding="utf-8")) if os.path.isfile(out60) else {}
    t6 = rep6.get("text") or {}
    check("③ 默认 → rc=0 且 n=60", rc == 0 and t6.get("n") == 60, f"rc={rc} n={t6.get('n')}")
    check("③ 默认确实是 60 条请求", len(SEEN) == 60, f"收到了 {len(SEEN)}")
    check("③ 默认日志打 [source] inline 60", "[source] inline 60" in out,
          [l for l in out.splitlines() if "[source]" in l][:1])

    # ④ 路径打错 → rc=2
    rc, out = run("--from-jsonl", os.path.join(tmp, "nope.jsonl"), "--limit", "30")
    check("④ 路径错 → rc=2", rc == 2, f"rc={rc}")
finally:
    srv.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: text 模式真的用 jsonl 名单（分母/日志/报告一致，名单 sha16 可对账）"
      if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
