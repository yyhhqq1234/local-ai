# -*- coding: utf-8 -*-
"""patch_start_gen7.py — 允许实例已 running 时直接接续（抢机成功后 start 不该再自杀）"""
p = 'train/lines/27b-kittyrev/kitty-rev/deploy/cloud/start_gen7.py'
s = open(p, encoding='utf-8').read()

old = '''    if st != "shutdown":
        print(f"[stop] 实例状态 {st}，不是干净 shutdown；克隆锁定/运行中都不动它")
        return 2

    print("[power] 开机…", flush=True)
    rc, out = run([PYP, "-X", "utf8", POWER, "on", "--wait", "480"], 600)
    print(out.strip().splitlines()[-3:] if out.strip() else out)
    if rc != 0:
        print("[stop] 开机失败")
        return 3'''

new = '''    # 抢机循环刚把实例开机 → status 已是 running，此时应直接接续上传/预检/开训，
    # 而不是报"不是干净 shutdown"自杀（2026-11-02 实测踩到：开机成功却没开训）
    if st not in ("shutdown", "running"):
        print(f"[stop] 实例状态 {st}（克隆锁定等），不动它")
        return 2
    if st == "running":
        print("[power] 实例已在运行，跳过开机", flush=True)
    else:
        print("[power] 开机…", flush=True)
        rc, out = run([PYP, "-X", "utf8", POWER, "on", "--wait", "480"], 600)
        print(out.strip().splitlines()[-3:] if out.strip() else out)
        if rc != 0:
            print("[stop] 开机失败")
            return 3'''

assert old in s, 'anchor missing'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8', newline='\n').write(s)
print('start_gen7 patched')
