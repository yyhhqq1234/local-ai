# -*- coding: utf-8 -*-
"""执行重建 + 验证"""
import subprocess, sys

result = subprocess.run(
    [sys.executable, r"D:\BaiduNetdiskDownload\Local-AI\_tmp\rebuild_mix_fixed.py"],
    capture_output=True, text=True
)
print(result.stdout[-3000:], end="")
if result.returncode != 0:
    print(f"\n[STDERR]\n{result.stderr[-2000:]}", end="")
    sys.exit(1)
print("\n[ALL OK]", end="")
