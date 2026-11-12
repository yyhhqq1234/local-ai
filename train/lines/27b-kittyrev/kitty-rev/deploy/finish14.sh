#!/bin/bash
# finish14.sh — 用多 range 分片补完 shard 14 的剩余部分。
# 依据 2026-10-22 13:21 实测：单次 range 10MB 能跑 1.11 MiB/s，
# 但 -C - 长连接只有 88 KB/s（hf-mirror 对长连接限速）→ 改短连接分片。
set -u

BASE=/root/autodl-tmp/kitty-rev/base/Huihui
F=model-00014-of-00018.safetensors
URL=https://hf-mirror.com/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main/model-00014-of-00018.safetensors
TOTAL=3979553664
PAR=6
SEG=47000000
PARTS=$BASE/_parts14

cd "$BASE" || exit 1
for p in $(pgrep -x curl); do kill -9 "$p" 2>/dev/null; done
sleep 2

START=$(stat -c %s "$F")
echo "[start] resume from $START / $TOTAL  (remain $(( (TOTAL-START)/1048576 )) MiB)"
[ "$START" -ge "$TOTAL" ] && { echo "[skip] already complete"; exit 0; }

rm -rf "$PARTS"; mkdir -p "$PARTS"

/root/miniconda3/bin/python - "$START" "$TOTAL" "$SEG" > /tmp/segs14.txt <<'PY'
import sys
s, e, seg = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
i = 0
while s < e:
    t = min(s + seg - 1, e - 1)
    print(i, s, t, t - s + 1)
    s = t + 1
    i += 1
PY
echo "[plan] segments = $(wc -l < /tmp/segs14.txt)  par=$PAR  seg=$((SEG/1048576)) MiB"

getseg() {
  i="$1"; s="$2"; e="$3"; n="$4"
  f="$PARTS/part-$(printf '%04d' "$i")"
  for try in 1 2 3; do
    curl -sS -L --connect-timeout 15 --max-time 600 -r "$s-$e" -o "$f" "$URL" 2>/dev/null
    got=$(stat -c %s "$f" 2>/dev/null || echo 0)
    [ "$got" -eq "$n" ] && return 0
    sleep $((try * 3))
  done
  echo "[BAD] seg $i got=$got want=$n"
  return 1
}
export -f getseg
export PARTS URL

t0=$(date +%s)
awk '{print $1, $2, $3, $4}' /tmp/segs14.txt | xargs -P "$PAR" -n 4 bash -c 'getseg "$@"' _
t1=$(date +%s)
dt=$((t1 - t0)); [ "$dt" -lt 1 ] && dt=1

echo "[download] elapsed ${dt}s"
echo "[parts] count=$(ls "$PARTS"/part-* 2>/dev/null | wc -l)  bytes=$(du -cb "$PARTS"/part-* 2>/dev/null | tail -1 | cut -f1)"
awk -v s="$(du -cb "$PARTS"/part-* 2>/dev/null | tail -1 | cut -f1)" -v d="$dt" \
  'BEGIN{printf "[rate] %.2f MiB/s\n", s/1048576/d}'

bad=$(ls -l "$PARTS"/part-* 2>/dev/null | awk '{print $5}' | wc -l)
echo "[verify] parts present = $bad"

# 按序拼接（用 sort 保证 0000..0NNN 顺序）
for f in $(ls "$PARTS"/part-* 2>/dev/null | sort); do cat "$f" >> "$F"; done
FIN=$(stat -c %s "$F")
echo "[final] size=$FIN  expect=$TOTAL  delta=$((FIN - TOTAL))"
if [ "$FIN" -eq "$TOTAL" ]; then
  rm -rf "$PARTS"
  echo "[OK] shard 14 complete"
else
  echo "[FAIL] size mismatch, parts kept at $PARTS"
  exit 1
fi
