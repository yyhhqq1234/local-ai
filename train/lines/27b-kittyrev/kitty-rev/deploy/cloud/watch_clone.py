#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""watch_clone.py —— AutoDL 克隆数据盘进度看门狗（DSH 后台任务用）

用途：克隆实例的数据盘是边拷边就绪的（du 会一路涨），本脚本每分钟采样一次，
      连续 3 次不涨即判定拷完，然后校验关键三棵树是否齐全并给结论。

输出：每行 `HH:MM:SS  <GB>  <速率MB/s>  状态`，末行给出 PASS/FAIL 汇总。
      后台任务日志：train/logs/clone-watch-<ts>.log

用法：
  python watch_clone.py                 # 默认每 60s 一次，最多 240 次
  python watch_clone.py --interval 60 --max 240
  python watch_clone.py --once          # 只采一次（手动看进度）
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rsh  # noqa: E402

# 期望存在的树（拷完必须齐）
EXPECT = [
    ("kitty-rev 部署/脚本树", "/root/autodl-tmp/kitty-rev"),
    ("27B 基座", "/root/autodl-tmp/base/Qwen3.8-27B"),
    ("训练产出 out", "/root/autodl-tmp/out"),
]


def du_gb(c, path="/root/autodl-tmp"):
    cmd = f"du -sb {path} 2>/dev/null | cut -f1"
    _in, out, _err = c.exec_command(cmd, timeout=300)
    v = out.read().decode().strip()
    try:
        return int(v) / 1e9
    except ValueError:
        return -1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--max", type=int, default=240)
    ap.add_argument("--stable-need", type=int, default=3)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    c = rsh.connect(timeout=60)
    prev, stable = None, 0
    t0 = time.time()

    for i in range(1, a.max + 1):
        gb = du_gb(c)
        now = time.strftime("%H:%M:%S")
        rate = ""
        if prev is not None and prev > 0:
            dr = gb - prev
            rate = f"{dr * 1000 / max(a.interval, 1):6.1f} MB/s"
            if gb <= prev:
                stable += 1
            else:
                stable = 0
        print(f"{now}  {gb:8.2f} GB  {rate:>10}  stable={stable}", flush=True)
        if a.once:
            break
        if stable >= a.stable_need:
            print(f"[done] 连续 {stable} 次无增长，判定拷贝结束（耗时 {(time.time()-t0)/60:.1f} min）", flush=True)
            break
        prev = gb
        time.sleep(a.interval)

    # 校验三棵树
    print("\n=== 关键树校验 ===", flush=True)
    ok_all = True
    for label, path in EXPECT:
        cmd = f"if [ -e {path} ]; then du -sh {path} 2>/dev/null | cut -f1; else echo MISSING; fi"
        _in, out, _err = c.exec_command(cmd, timeout=300)
        v = out.read().decode().strip()
        ok = v != "MISSING"
        ok_all &= ok
        print(f"  {'OK  ' if ok else 'MISS'} {label:20s} {path}  {v}", flush=True)

    # 关键文件抽查
    print("\n=== 关键文件抽查 ===", flush=True)
    FILES = [
        ("27B 基座 config", "/root/autodl-tmp/base/Qwen3.8-27B/config.json"),
        ("gen3_1p 训练数据", "/root/autodl-tmp/kitty-rev/kitty-rev/data/gen2/gen3_1p-nsfw-kitty.jsonl"),
        ("gen3_1 训练数据", "/root/autodl-tmp/kitty-rev/kitty-rev/data/gen2/gen3_1-nsfw-kitty.jsonl"),
        ("续训源 adapter-600", "/root/autodl-tmp/init/gen3_1-adapter-600/adapter_model.safetensors"),
        ("训练脚本 train_kitty.py", "/root/autodl-tmp/kitty-rev/kitty-rev/scripts/train_kitty.py"),
        ("5090 训练脚本 gen3_1p_5090.sh", "/root/autodl-tmp/kitty-rev/kitty-rev/deploy/cloud/gen3_1p_5090.sh"),
    ]
    for label, path in FILES:
        cmd = f"if [ -f {path} ]; then stat -c%s {path}; else echo MISSING; fi"
        _in, out, _err = c.exec_command(cmd, timeout=120)
        v = out.read().decode().strip()
        ok = v != "MISSING"
        if ok and v.isdigit():
            v = f"{int(v)/1048576:.1f} MB"
        print(f"  {'OK  ' if ok else 'MISS'} {label:26s} {v}", flush=True)
        ok_all &= ok

    print(f"\n[VERDICT] {'PASS 可以进 pre/train' if ok_all else 'FAIL 有缺失，需补传或等克隆继续'}", flush=True)
    c.close()
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
