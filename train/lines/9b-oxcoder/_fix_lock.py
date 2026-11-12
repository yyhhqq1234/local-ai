#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把两个训练链里的 flock（git-bash 不存在）换成 pidfile 锁"""
import io, os, re

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)))

NEW = '''# ── 单实例锁（pidfile 版：git-bash 没有 flock）──
LOCK="$L/.train.pid"
if [ -f "$LOCK" ]; then
  OLDPID=$(cat "$LOCK" 2>/dev/null || echo 0)
  if [ -n "$OLDPID" ] && [ "$OLDPID" != "0" ] && kill -0 "$OLDPID" 2>/dev/null; then
    log "已有训练 pid=$OLDPID 在跑（$LOCK）→ 本次退出"
    exit 3
  fi
  log "旧锁残留 pid=$OLDPID 已死 → 清理"
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT
log "拿到训练锁 pid=$$"
'''

# 1) _resume_2b_v4.sh：替换整段 exec 9>... flock
p1 = os.path.join(BASE, "_resume_2b_v4.sh")
s = io.open(p1, encoding="utf-8").read()
s = re.sub(
    r'# ── 单实例锁：整个训练期只允许一个训练进程 ──\nexec 9>.*?\nlog "拿到训练锁 pid=\$\$"\n',
    NEW, s, flags=re.S)
io.open(p1, "w", encoding="utf-8").write(s)
print(f"[{'OK' if 'pidfile' in s else 'WARN'}] {os.path.basename(p1)}")

# 2) zb_v6_chain.sh：替换 flock -w 段
p2 = os.path.join(BASE, "zb_v6_chain.sh")
s2 = io.open(p2, encoding="utf-8").read()
s2 = re.sub(
    r'# 单实例锁：等 2B v4 续训让出（最多 14h）\nexec 9>.*?log "拿到训练锁 pid=\$\$"\n',
    NEW, s2, flags=re.S)
io.open(p2, "w", encoding="utf-8").write(s2)
print(f"[{'OK' if 'pidfile' in s2 else 'WARN'}] {os.path.basename(p2)}")

for p in (p1, p2):
    body = io.open(p, encoding="utf-8").read()
    bad = [l for l in body.split("\n") if "flock" in l]
    print(f"  {os.path.basename(p)}: 残留 flock 行 {len(bad)}")
