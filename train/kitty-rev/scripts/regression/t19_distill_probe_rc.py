#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""t15_distill_probe_rc.py -- 探活失败（curl 连不上）不许伪装成 HTTP 判读。

缺陷现象
    rc, out, err = curl([..., "-o", "/dev/null", "-w", "%{http_code}", ...])
    code = (out or "").strip()
    verdict = {...}.get(code, f"HTTP{code}")
    —— rc（curl 退出码）被丢掉。连不上/DNS 错/TLS 错/超时时 stdout 是空串，
    于是 verdict 落成 "HTTP"（后面没有码），打印出来像一次 HTTP 层判定。
后果
    探活表里最该被看见的"根本没连上"（rc=6/7/28/35/60）显示成一列 HTTP 结果；
    真实故障与"服务端返回了奇怪的码"混在一起，排查方向直接跑偏。
正确的断言
    rc != 0 或 code 为空 → CURL-ERR，且明细里带 rc；
    正常码仍按原表判读（200 OK / 401 BAD-KEY / 403 FORBIDDEN / 404 NO-ENDPOINT）。
如果这条 FAIL 说明什么
    又有人只读 -w 的输出、把 curl 退出码丢掉（= 第 8 例同族的"缺失被默认值吸收"）。
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITTY = os.path.dirname(os.path.dirname(HERE))
# 可选 argv[1]：指向另一份 distill_cot.py（变异对照用）；run_all.py 不传参。
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KITTY, "scripts",
                                                            "distill_cot.py")
sys.path.insert(0, os.path.dirname(SCRIPT))

fails = []
try:
    dc = importlib.import_module(os.path.splitext(os.path.basename(SCRIPT))[0])
except Exception as e:
    print(f"\nFAIL: 载入 distill_cot 失败（{type(e).__name__}: {e}）")
    sys.exit(1)

if not hasattr(dc, "probe_verdict"):
    print("\nFAIL: distill_cot 缺 probe_verdict()（回归脚本的锚点）")
    sys.exit(1)


def check(name, cond, detail=""):
    print(f"[{'ok ' if cond else 'BAD'}] {name}  {detail}")
    if not cond:
        fails.append(f"{name}: {detail}")


# 正常码
for code, want in (("200", "OK"), ("401", "BAD-KEY"), ("403", "FORBIDDEN"),
                   ("404", "NO-ENDPOINT"), ("418", "HTTP418")):
    v, d = dc.probe_verdict(0, code + "\n", "")
    check(f"rc=0 code={code} → {want}", v == want, f"{v} | {d}")

# 连接层失败：rc != 0 且 stdout 空 → 必须是 CURL-ERR
for rc in (6, 7, 28, 35, 60):
    v, d = dc.probe_verdict(rc, "", "curl: (7) Failed to connect")
    check(f"rc={rc} 空码 → CURL-ERR", v == "CURL-ERR", f"{v} | {d}")
    check(f"rc={rc} 明细带 rc", f"rc={rc}" in d, d)

# rc=0 但空码（后端把 -w 吞了）同样不能当 HTTP
v, d = dc.probe_verdict(0, "  ", "")
check("rc=0 空码 → CURL-ERR", v == "CURL-ERR", f"{v} | {d}")

# 不许出现旧的 "HTTP"（无码）判读
v, _ = dc.probe_verdict(7, "", "")
check("不含裸 'HTTP' 判读", v != "HTTP", v)

print("\nPASS: 连接失败显式 CURL-ERR，HTTP 码判读不变" if not fails else f"\nFAIL: {fails}")
sys.exit(0 if not fails else 1)
