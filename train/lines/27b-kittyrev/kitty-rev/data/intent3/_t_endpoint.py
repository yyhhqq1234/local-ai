# -*- coding: utf-8 -*-
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ro", "run_overrefusal.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
cases = [
    ("http://127.0.0.1:1234",                          "http://127.0.0.1:1234/v1/chat/completions"),
    ("http://127.0.0.1:1234/",                          "http://127.0.0.1:1234/v1/chat/completions"),
    ("http://127.0.0.1:1234/v1",                        "http://127.0.0.1:1234/v1/chat/completions"),
    ("http://127.0.0.1:1234/v1/chat/completions",       "http://127.0.0.1:1234/v1/chat/completions"),
    ("http://127.0.0.1:1234/v1/chat/completions/",      "http://127.0.0.1:1234/v1/chat/completions"),
    ("http://host/proxy/v1",                            "http://host/proxy/v1/chat/completions"),
    ("http://host/proxy/v1/chat/completions",           "http://host/proxy/v1/chat/completions"),
]
bad = 0
for raw, want in cases:
    try:
        got = m.endpoint_url(raw)
    except SystemExit:
        got = "<DIED>"
    ok = (got == want)
    if not ok: bad += 1
    print(("PASS" if ok else "FAIL"), repr(raw), "->", got, ("" if ok else f"WANT {want}"))
print("RESULT", "ALL-PASS" if bad == 0 else f"{bad}-FAIL")
sys.exit(1 if bad else 0)
