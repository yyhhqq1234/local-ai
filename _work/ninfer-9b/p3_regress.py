# p3_regress.py — 9B 输出行数修复后的回归验收
# 口径：5 prompt × 3 轮 = 15/15；附加 system+user / essay 失败例；
#       检查 engine log 的 NaN / 形状未命中；记录 prefill / decode 速度。
# 纪律：只按 Path 杀本档位引擎；绝不按名杀。
import json
import os
import re
import subprocess
import sys
import time
import http.client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = r"D:\BaiduNetdiskDownload\Local-AI"
EXE = os.path.join(ROOT, r"_tools\ninfer-build\apps\ninfer-serve.exe")
MODEL = os.path.join(ROOT, r"train\lines\9b-oxcoder\out\kittyrev-oxcoder9b-nsfw-gate-full-GSQ.ninfer")
WORK = os.path.join(ROOT, r"_work\ninfer-9b")
PORT = 1681
REQ = os.path.join(WORK, "p3-regress.reqlog.jsonl")
ENG = os.path.join(WORK, "p3-regress.engine.log")

SETS = [
    ("p1-2+2", "What is 2+2?", 32, "4"),
    ("p2-hello", "Say hello in Chinese.", 24, "你好"),
    ("p3-gdn", "Explain what a gated delta network is in one sentence.", 48, "delta"),
    ("p4-pyrev", "Write a Python one-liner to reverse a string.", 64, "[::-1]"),
    ("p5-unittest", "List 3 benefits of unit testing.", 128, "test"),
]
EXTRA = [
    ("sys", [{"role": "system", "content": "You are a helpful assistant."},
             {"role": "user", "content": "What is 2+2?"}], 16, "4"),
    ("essay", [{"role": "user", "content": "Write a 300-word essay about why local inference matters."}],
     24, None),
]

PS_LIST = (
    "Get-CimInstance Win32_Process -Filter \"Name = 'ninfer-serve.exe'\" | "
    "ForEach-Object { Write-Output ($_.ProcessId.ToString() + [char]9 + [string]$_.ExecutablePath) }"
)


def ninfer_processes():
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_LIST],
                       capture_output=True, text=True)
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            out.append((int(parts[0].strip()), parts[1].strip()))
    return out


def kill_own_engine():
    for pid, path in ninfer_processes():
        if path.lower() == EXE.lower():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def http_json(port, path, payload=None, timeout=300):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        if payload is None:
            c.request("GET", path)
        else:
            c.request("POST", path, body=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
        return json.loads(c.getresponse().read())
    finally:
        c.close()


GARBAGE = re.compile(r"[A-Za-z0-9+/]{14,}")


def looks_garbled(text):
    if not text.strip():
        return True, "empty"
    if "\ufffd" in text:
        return True, "replacement-char"
    m = GARBAGE.search(text)
    if m:
        s = m.group(0)
        mixed = any(c.islower() for c in s) and any(c.isupper() for c in s)
        if mixed:
            return True, "base64-like:" + s[:24]
    return False, ""


def parse_reqlog(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event") != "request_done":
                continue
            r = d.get("result", {})
            f_out = d.get("first_output_timing", {})
            state = f_out.get("context_transfers", {}).get("state", {})
            t = d.get("timings_seconds", {})
            pt, ct = r.get("prompt_tokens") or 0, r.get("completion_tokens") or 0
            pf, dec = t.get("prefill") or 0, t.get("decode") or 0
            rows.append({
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "hit": r.get("prefix_cache_hit_tokens"),
                "path": r.get("prefix_reuse_path"),
                "units_prefill": d.get("engine_timing", {}).get("units", {}).get("prefill"),
                "state_d2h": state.get("d2h", {}).get("bytes"),
                "ids_head": (r.get("generated_token_ids") or [])[:8],
                "prefill_tok_s": round(pt / pf, 1) if pf else None,
                "decode_tok_s": round(ct / dec, 1) if dec else None,
            })
    return rows


def main():
    kill_own_engine()
    time.sleep(0.8)
    for p in (REQ, ENG):
        if os.path.exists(p):
            os.remove(p)
    args = [EXE, MODEL, "--max-context", "4096", "--greedy", "--host-context-mib", "2048",
            "--prefill-chunk", "128", "--no-thinking", "--port", str(PORT),
            "--request-log-jsonl", REQ, "--log-level", "trace"]
    log = open(ENG, "wb")
    p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    results = []
    try:
        ready = False
        for _ in range(180):
            time.sleep(0.5)
            if p.poll() is not None:
                break
            try:
                http_json(PORT, "/v1/models", timeout=2)
                ready = True
                break
            except Exception:
                pass
        if not ready:
            print("ENGINE NOT READY")
            return
        mid = http_json(PORT, "/v1/models")["data"][0]["id"]
        for r in range(1, 4):
            for name, prompt, mt, keyword in SETS:
                results.append(run_one(mid, "r%d-%s" % (r, name),
                                       [{"role": "user", "content": prompt}], mt, keyword))
        for name, msgs, mt, keyword in EXTRA:
            results.append(run_one(mid, name, msgs, mt, keyword))
        time.sleep(0.6)
    finally:
        try:
            p.kill()
        except Exception:
            pass
        log.close()
        time.sleep(0.5)
        kill_own_engine()

    rows = parse_reqlog(REQ)
    with open(ENG, "rb") as f:
        eng_text = f.read().decode("utf-8", "replace")
    bad_markers = [m for m in ("q8-miss", "bf16-miss", "unsupported shape", "NaN", "nan")
                   if m in eng_text]

    ok = sum(1 for x in results if x["ok"])
    nonempty = sum(1 for x in results if x["chars"] > 0)
    clean = sum(1 for x in results if not x["garbled"])
    kw_ok = sum(1 for x in results if x["keyword_hit"])
    print("=== 5x3 = %d/%d OK (nonempty=%d, clean=%d, keyword=%d) ===" %
          (ok, len(results), nonempty, clean, kw_ok))
    for x in results:
        print("  %-14s chars=%-4d ok=%-5s garb=%-22s kw=%-5s >>> %s" %
              (x["name"], x["chars"], x["ok"], x["garbled"] or "-", x["keyword_hit"], x["head"]))
    print("=== reqlog %d rows ===" % len(rows))
    for i, q in enumerate(rows):
        print("  %2d prompt=%-3s hit=%-3s path=%-10s units=%-3s d2h=%-9s prefill=%-7s decode=%-6s ids=%s" %
              (i + 1, q["prompt_tokens"], q["hit"], q["path"], q["units_prefill"],
               q["state_d2h"], q["prefill_tok_s"], q["decode_tok_s"], q["ids_head"]))
    print("=== engine log bad markers: %s ===" % (bad_markers or "NONE"))
    print("=== remaining ninfer processes: %s ===" % ninfer_processes())
    out = os.path.join(WORK, "p3-regress-result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"results": results, "reqlog": rows, "bad_markers": bad_markers,
                   "remaining": ninfer_processes()}, f, ensure_ascii=False, indent=2)
    print("result json:", out)


def run_one(mid, name, msgs, mt, keyword):
    rec = {"name": name, "ok": False, "chars": 0, "head": "", "garbled": "", "keyword_hit": None}
    try:
        d = http_json(PORT, "/v1/chat/completions",
                      {"model": mid, "messages": msgs, "max_tokens": mt,
                       "temperature": 0, "stream": False})
        t = d["choices"][0]["message"]["content"] or ""
        rec["chars"] = len(t)
        rec["head"] = " ".join(t.split())[:95]
        bad, why = looks_garbled(t)
        rec["garbled"] = why
        rec["keyword_hit"] = (keyword in t) if keyword else None
        rec["ok"] = (len(t) > 0) and not bad
    except Exception as e:
        rec["head"] = repr(e)
        rec["garbled"] = "request-error"
    return rec


if __name__ == "__main__":
    main()
