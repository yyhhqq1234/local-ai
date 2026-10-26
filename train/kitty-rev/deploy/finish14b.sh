#!/bin/bash
# finish14b.sh — 用 hf-mirror.net 补齐 shard14 的分片，然后按序拼接 + 结构校验。
# 段内续传用 `-r (s+got)-e --append`（不能用 -C -，因为服务器 range 是绝对偏移）。
set -u

BASE=/root/autodl-tmp/kitty-rev/base/Huihui
F=model-00014-of-00018.safetensors
URL=https://hf-mirror.net/huihui-ai/Huihui-Qwen3.8-27B-abliterated/resolve/main/model-00014-of-00018.safetensors
TOTAL=3979553664
PARTS=$BASE/_parts14
PAR=${PAR:-8}
SEGS=/tmp/segs14.txt

cd "$BASE" || exit 1
[ -f "$SEGS" ] || { echo "[FATAL] 缺 $SEGS"; exit 2; }
[ -d "$PARTS" ] || { echo "[FATAL] 缺 $PARTS"; exit 2; }

echo "=== [1] inventory ==="
need=0; done_n=0
while read -r i s e n; do
  f="$PARTS/part-$(printf '%04d' "$i")"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  if [ "$got" -eq "$n" ]; then done_n=$((done_n+1)); else need=$((need+1)); fi
done < "$SEGS"
echo "  complete=$done_n  incomplete=$need  total_segs=$(wc -l < "$SEGS")"

getseg() {
  i="$1"; s="$2"; e="$3"; n="$4"
  f="$PARTS/part-$(printf '%04d' "$i")"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  [ "$got" -eq "$n" ] && return 0
  for try in 1 2 3 4; do
    got=$(stat -c %s "$f" 2>/dev/null || echo 0)
    [ "$got" -eq "$n" ] && return 0
    rs=$((s + got))
    curl -sS -L --connect-timeout 15 --max-time 300 -r "$rs-$e" --append -o "$f" "$URL" 2>/dev/null
    sleep $((try * 2))
  done
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  [ "$got" -eq "$n" ] || { echo "[BAD] seg $i got=$got want=$n"; return 1; }
  return 0
}
export -f getseg
export PARTS URL

echo "=== [2] fill missing (par=$PAR, host=hf-mirror.net) ==="
t0=$(date +%s)
awk '{print $1, $2, $3, $4}' "$SEGS" | xargs -P "$PAR" -n 4 bash -c 'getseg "$@"' _
t1=$(date +%s); dt=$((t1-t0)); [ "$dt" -lt 1 ] && dt=1

echo "=== [3] verify all segments ==="
bad=0
while read -r i s e n; do
  f="$PARTS/part-$(printf '%04d' "$i")"
  got=$(stat -c %s "$f" 2>/dev/null || echo 0)
  [ "$got" -eq "$n" ] || { echo "  BAD seg $i got=$got want=$n"; bad=$((bad+1)); }
done < "$SEGS"
echo "  bad_segments=$bad  elapsed=${dt}s"

if [ "$bad" -ne 0 ]; then
  echo "[FATAL] 有段不完整，不拼装。保留 $PARTS 供续传。"
  exit 3
fi

echo "=== [4] stitch ==="
CUR=$(stat -c %s "$F")
echo "  main before = $CUR"
for f in $(ls "$PARTS"/part-* | sort); do cat "$f" >> "$F"; done
FIN=$(stat -c %s "$F")
echo "  main after  = $FIN   expect=$TOTAL  delta=$((FIN-TOTAL))"
if [ "$FIN" -ne "$TOTAL" ]; then
  echo "[FATAL] 拼接后大小不符（可能主文件起点与段起点不一致）"
  exit 4
fi

echo "=== [5] safetensors structure check ==="
/root/miniconda3/bin/python - "$F" <<'PY'
import json, os, struct, sys
p = sys.argv[1]
with open(p, 'rb') as f:
    n = struct.unpack('<Q', f.read(8))[0]
    blob = f.read(n)
h = json.loads(blob.decode('utf-8'))
mx = max(int(v['data_offsets'][1]) for k, v in h.items() if k != '__metadata__')
need = 8 + n + mx
sz = os.path.getsize(p)
print("  header=%d tensors=%d expect=%d actual=%d %s"
      % (n, len(h) - (1 if '__metadata__' in h else 0), need, sz,
         "PASS" if need == sz else "FAIL"))
sys.exit(0 if need == sz else 1)
PY
rc=$?
if [ "$rc" -eq 0 ]; then
  rm -rf "$PARTS"
  echo "[OK] shard14 complete & structurally valid"
else
  echo "[FATAL] 结构校验失败，保留 $PARTS"
  exit 5
fi
